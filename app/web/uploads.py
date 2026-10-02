from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler
from .images import MAX_UPLOAD_BYTES


class BoundedUploadHandler(FileUploadHandler):
    """Bound the whole request before Django spills an unbounded file to disk."""
    def __init__(self, request=None):
        super().__init__(request)
        self.total=0

    def receive_data_chunk(self,raw_data,start):
        self.total+=len(raw_data)
        if self.total>MAX_UPLOAD_BYTES:
            raise RequestDataTooBig('Photo upload exceeds the 12 MiB request limit')
        return raw_data

    def file_complete(self,file_size):
        return None
