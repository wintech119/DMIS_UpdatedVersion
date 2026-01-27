
## Deployment

This document describes a deployment setup for the DRIMS app.

The deployment was tested on AlmaLinux release 9.7 (Moss Jungle Cat) Differences with RHEL are noted where known.

### OS Preparation

Typically, Python based apps are installed in a virtualenv to prevent clashes with versions of libraries used by the system. Additionally, to prevent unauthorized and unintended execution of some program, we will create a user to own the files and run the program.

**Step 0 and Step 1 should be executed as root or using `sudo`**. All the commands in both steps require root permissions.

#### Step 0: Install OS Prerequisites

This application uses the Web-server gateway interface protocol (WSGI). We can launch it using an HTTP server. But, instead we will launch it as a WSGI app and have nginx talk directly to it using an optimized binary protocol.

To do this, we will use the WSGI server named `uwsgi`. We will also install the Python3 plugin so uwsgi can launch a python app.

It is located in the EPEL repository with nginx. So, first we enable EPEL

`dnf config-manager --set-enabled crb`
` dnf install https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm`

Then we install nginx and uwsgi. We will configure them in Step 6 below.

`dnf install uwsgi uwsgi-plugin-python3 nginx`

#### Step 1: Add a responsible user

This user will own the application code and and generated files. We will also install the app to this user's home directory.

Let's call the user **drims** and put the home directory under /var/local/.

`useradd --system --user-group -create-home --home-dir  /var/local/drims --shell /bin/bash --password x drims`

or 

`useradd -rUmd /var/local/drims -s /bin/bash -p x drims`

#### Step 1.5 Install PostgreSQL (optional).

If this is a dev server and will not be granted a postgres instance, follow instructions at https://www.postgresql.org/download/linux/redhat/ to install PostgreSQL 16.


### Install the Application

The current version of the application has not been setup as an installable package. We will put the files in a folder and setup the web server to serve from there.

Steps 2 and 3 are executed as that drims user we created in the previous step. Since we disabled his password, we have to use sudo to become that user.

`sudo -iu drims`

You should now have a bash shell as the drims user.

#### Step 2: Create VirtualEnv and other directories

Let's make a directory for the virtualenvs, the software and for downloads.

`mkdir venvs, code, downloads`

Download the software from: 

`cd ~/downloads`
`wget -O drims-new-main.zip https://github.com/wintech119/DrimsNewBuildv2/archive/refs/heads/main.zip`

If you download it multiple times, wget will create subsequent number versions. Use the latest (e.g. 3)

`cd ~/code/`
`unzip ~/downloads/main.zip.3`

Since future downloads will also extract to the same name, let's rename this one and create a symlink so we can upgrade and downgrade at will.

`mv DrimsNewBuildv2-main main-$(date +%Y%m%d)`
`ln -s main-$(date +%Y%m%d) current`

If this is not your first install, you may need to `rm current` first.

To make the static media show up at the same place all the time, we'll make a symlink to it using the "current" link:

```
mkdir ~/code/static-site
ln -s ~/code/current/static ~/code/static-site/static
```

We also need to set some permissions so that UWSGI can get to the files:

`chmod a+rx /var/local/drims`


#### Step 3: Install app dependencies

Create a virtualenv inside the venvs folder. Let's call it env001

`python3 -m venv ~/venvs/env001`

Then, we activate the virtualenv and install the app dependencies

`source ~/venvs/env001`
`pip install -r ~/code/current/requirements.txt`

### Configure the runtime environment

#### Step 4: Configure UWSGI (Application Server)

The configuration for uwsgi presented below is for the site itself. 
This file should be /etc/uwsgi.d/001-drims.ini

```
[uwsgi]

socket = 0.0.0.0:2022
chdir = /var/local/drims/code/current
touch_reload = /var/local/drims/reloader.txt
pythonpath = /var/local/drims/code/current

virtualenv = /var/local/drims/venvs/env001

module = wsgi:flask_app

uid = drims
gid = drims


vacuum = True
max-requests = 15000

workers = 4
socket-timeout = 15

# put timestamps into the log
log-date = true
logto = /var/log/uwsgi/drims.log

pidfile = /run/uwsgi/drims.pid

plugins-dir = /usr/lib64/uwsgi/
plugin = python3

# Read Environment variables from /var/local/drims/uwsgi.env
for-readline = /var/local/drims/uwsgi.env
  env = %(_)
endfor =

```

the uwsgi config mentions a reloader file. Let's create that:

`touch /var/local/drims/reloader.txt`

It's okay if that file is empty. 

And we need to set the correct permission on the config file or the UWSGI emperor won't start it:

`chown uwsgi:uwsgi /etc/uwsgi.d/001-drims.ini`

Finally, we need to create the file with the environment variables. The config above puts that file in the drims user's home directory. 

`touch /var/local/drims/uwsgi.env`

That file can go anywhere and be named anything. But, it **needs** to have at least these three variables:

```
DATABASE_URL=postgresql://dbuser:dbuserpwd@pghost:port/dbname
SECRET_KEY=some_random-string:used_for_encrypting/user/sessions

```


#### Step 5: Configure media server (nginx)

This nginx instance will run on the application server purely for serving up static media.

The following is for the site itself. It does not include the base config. 

```
server {
    listen 2020;
    server_name drims-media _;

    root /var/local/drims/code/static-site;

}


```

#### Step 6: Configure front-end server (nginx)

This is the frontend webserver. The config below is just parts.

```

upstream drims_app {
   server 127.0.0.1:2022;
}

upstream drims_media {
    server 127.0.0.1:2020;
}

server {

    listen 443;
    server_name drims.odpem.gov.jm _;

    location /static {
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass drims_media;
    }

    location @uwsgi_to_app {
        include uwsgi_params;
        uwsgi_pass drims_app;
        uwsgi_read_timeout 15;
    }

    location / {
        try_files $uri @uwsgi_to_app;
    }
}


```

You can finish up this frontend nginx config.
