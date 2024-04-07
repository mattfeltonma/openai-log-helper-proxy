FROM ubuntu:20.04

# Setup SSH on server
RUN apt-get -y install openssh-server
RUN echo "root:Docker!" | chpasswd
RUN ssh-keygen -A
COPY ./sshd_config /etc/ssh/.
EXPOSE 2222

RUN apt-get update && apt-get -y install --no-install-recommends wget gnupg ca-certificates gcc gettext-base && \
    curl -fsSL https://openresty.org/package/pubkey.gpg | gpg --dearmor > /usr/share/keyrings/openresty.gpg && \
    codename=`grep -Po 'VERSION="[0-9]+ \(\K[^)]+' /etc/os-release` && \
    echo "deb [signed-by=/usr/share/keyrings/openresty.gpg] http://openresty.org/package/debian $codename openresty" | tee /etc/apt/sources.list.d/openresty.list > /dev/null && \
    apt-get update && \
    apt-get -y install openresty && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/run/openresty && \
    ln -sf /dev/stdout /usr/local/openresty/nginx/logs/access.log && \
    ln -sf /dev/stderr /usr/local/openresty/nginx/logs/error.log

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y && apt-get install --reinstall libc6-dev -y
ENV PATH="/root/.cargo/bin:${PATH}"

RUN mkdir -p /opt/loghelper
COPY loghelper/requirements.txt /opt/loghelper
RUN cd /opt/loghelper && pip install -r requirements.txt   

RUN wget https://raw.githubusercontent.com/openresty/docker-openresty/master/nginx.conf && \
    mv nginx.conf /usr/local/openresty/nginx/conf

RUN mkdir -p /etc/nginx/conf.d
RUN mkdir -p /etc/nginx/templates
COPY default.conf.template /etc/nginx/templates

 

COPY entry.sh /opt
COPY loghelper/ /opt/loghelper

RUN touch /var/log/nginx_access.log
RUN touch /var/log/loghelper_openai.log

ENTRYPOINT [ "bash", "/opt/entry.sh" ]