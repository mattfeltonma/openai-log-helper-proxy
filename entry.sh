#!/bin/bash
envsubst '$DNS_SERVER $GEN_AI_GATEWAY_FQDN' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

nohup python /opt/loghelper/processor.py 2>&1 &
/usr/local/openresty/bin/openresty -g "daemon off;"