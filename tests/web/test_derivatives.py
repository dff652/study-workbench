from pathlib import Path
from PIL import Image
from django.db import DatabaseError,transaction,connection
from unittest.mock import patch
from django.test import TransactionTestCase
from app.persistence import services as core
from app.web import derivatives,services
from app.web.models import ImageDerivative
from tests.web.test_services import ManualServicesTests,key,image_bytes


class DerivativeTests(TransactionTestCase):
    setUp=ManualServicesTests.setUp
    tearDown=ManualServicesTests.tearDown
    page=ManualServicesTests.page

    def create(self,page,operation='crop',**kwargs):
        preview=services.preview_file(self.owner,page,0)
        return derivatives.create_derivative(self.owner,page,operation=operation,
            rotation=0,preview_sha256=preview.sha256,display_bbox=[0,0,40,50],request_key=key(),**kwargs)

    def test_original_unchanged_crop_mask_contrast_append_and_file_authorization(self):
        page=self.page(raw=image_bytes('gray'))
        original=services.page_detail(self.owner,page)['page'].image
        original_path=services.asset_path(original.payload['storage_key'],original.sha256)
        before=original_path.read_bytes()
        cropped=self.create(page)
        erased=self.create(page,'erase',masks=[[0,0,5,5]])
        enhanced=self.create(page,'contrast',contrast=2)
        self.assertEqual((cropped.width,cropped.height),(40,50))
        for row in (cropped,erased,enhanced):
            self.assertEqual(row.original_sha256,original.sha256)
            self.assertTrue(row.lossy_description)
            self.assertEqual(row.parameters['coordinate_space'],'original_pixels')
            path=derivatives.derivative_file(self.owner,row.pk)[1]
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(core.PersistenceError):derivatives.derivative_file(self.other,row.pk)
        with Image.open(derivatives.derivative_file(self.owner,erased.pk)[1]) as image:
            self.assertEqual(image.getpixel((0,0)),(255,255,255))
            self.assertEqual(image.getpixel((5,5)),(128,128,128))
        self.assertEqual(original_path.read_bytes(),before)
        self.assertEqual(ImageDerivative.objects.count(),3)
        from django.urls import reverse
        self.client.force_login(self.owner)
        response=self.client.get(reverse('web:derivative_file',args=[cropped.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('web:derivative_file',args=[cropped.pk])).status_code,404)
        with self.assertRaises(DatabaseError),transaction.atomic():ImageDerivative.objects.filter(pk=cropped.pk).update(operation='erase')
        with self.assertRaises(DatabaseError),transaction.atomic():ImageDerivative.objects.all().delete()
        with self.assertRaises(DatabaseError),transaction.atomic():
            ImageDerivative.objects.create(page_id=page,original_image=original,created_by=self.owner,
                operation='crop',parameters={},original_sha256='0'*64,sha256='a'*64,
                storage_key='never-written.png',width=1,height=1,lossy_description='synthetic mismatch',
                request_key=key(),fingerprint='b'*64)

    def test_rotated_geometry_replay_conflict_and_mask_bounds(self):
        page=self.page();preview=services.preview_file(self.owner,page,90)
        inputs=dict(operation='crop',rotation=90,preview_sha256=preview.sha256,
            display_bbox=[10,5,40,30],request_key=key())
        row=derivatives.create_derivative(self.owner,page,**inputs)
        self.assertEqual(row.parameters['original_bbox'],[5,20,30,50])
        self.assertEqual(row.pk,derivatives.create_derivative(self.owner,page,**inputs).pk)
        with self.assertRaises(core.PersistenceError):derivatives.create_derivative(self.owner,page,**{**inputs,'display_bbox':[1,1,10,10]})
        for masks in ([],[[0,0,50,50]],'bad'):
            with self.assertRaises(core.PersistenceError):self.create(page,'erase',masks=masks)
        with self.assertRaises(core.PersistenceError):derivatives.create_derivative(self.viewer,page,**{**inputs,'request_key':key()})

    def test_insert_and_commit_failure_leave_no_orphan_and_keep_successful_file(self):
        page=self.page();success=self.create(page)
        _,kept=derivatives.derivative_file(self.owner,success.pk)
        before=set(Path(self.temporary.name).glob('derivatives/**/*.png'))
        with patch.object(ImageDerivative.objects,'create',side_effect=DatabaseError('synthetic insert failure')):
            with self.assertRaises(DatabaseError):self.create(page)
        self.assertEqual(set(Path(self.temporary.name).glob('derivatives/**/*.png')),before)
        with patch.object(connection,'commit',side_effect=DatabaseError('synthetic commit failure')):
            with self.assertRaises(DatabaseError):self.create(page)
        self.assertEqual(set(Path(self.temporary.name).glob('derivatives/**/*.png')),before)
        self.assertTrue(kept.exists())
        self.assertEqual(ImageDerivative.objects.count(),1)
