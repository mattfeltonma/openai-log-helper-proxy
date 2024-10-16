#!/bin/bash
envsubst '$DNS_SERVER' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
envsubst '$GEN_AI_GATEWAY_FQDN' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

nohup python /opt/loghelper/processor.py 2>&1 &
/usr/local/openresty/bin/openresty -g "daemon off;"