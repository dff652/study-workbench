FROM caddy@sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d

# The proxy listens above 1024. A file capability conflicts with cap_drop: ALL.
RUN setcap -r /usr/bin/caddy

ARG SWB_RESOURCE_OWNER=manual
LABEL com.study-workbench.resource-owner=${SWB_RESOURCE_OWNER}
