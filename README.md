# log-to-rabbitmq

## Introduction
At Honkmobile we perform a large amount of log analysis, click-stream tracking, and loading into a data warehouse. Importing web logs following regular daily rotation is functional, but supporting our BI needs requires near real-time import from our API and web servers into our reporting platform. This script is used to emit logs from various applications into RabbitMQ, from which a set of workers consume the logs appropriately.

In casual testing we were able to produce more than 10,000 messages per second with this script. Any bottleneck in our environment is in RabbitMQ's ability to absorb the message stream fast enough, though theoretically it may be possible to swamp the host that produces logs. This would not be very likely in any real-world application.

## Requirements
This script requires Python 2.x. We have only tested it on 2.7, though it will likely work with earlier versions. Python 3 support is not available as we use librabbitmq, which unfortunately does not support Python 3 yet (nod to the librabbitmq team).

A *NIX system is also required. The current version does not support Windows, and cannot as it does not understand signals. Alternative handling is possible but has not been implemented. If you're in a Windows shop and want to tackle that then we'll appreciate it!

## Usage
First you will need a config file. You can create one with one command:

    ./log_to_rabbitmq.py -m > log_to_rabbitmq.conf

Using it in bulk is simple enough:

    ./log_to_rabbitmq.py -c /path/to/config < /file/to/consume

Or like so:

    cat /file/to/consume | ./log_to_rabbitmq.py -c /path/to/config

However as the script does not exit on EOF you won't want to run it like this. The intention is to have it listen to a named pipe, thereby pushing logs into RabbitMQ immediately and indefinitely, rather than in bulk. Here is something similar to what we do for Nginx logs.

First you'll need a pipe:

    mkfifo /var/log/nginx/access.log

Now start the script using this as input:

    ./log_to_rabbitmq.py -c /path/to/config < /var/log/nginx/access.log 2>/some/log/file

That's all there is to it. So long as your config file is healthy you should be seeing access logs streaming into the queue that you have requested. Wrap this command in an init script and have it start *before* Nginx and you should be good to go. Note that with Nginx you *must* have the listener on the other end of the pipe already running otherwise your server will block!

## Installation
Installing the script is only as complicated as downloading it and saving it to disk. However you will require some additional Python modules that we rely on. This command will install your prerequisites:

    pip install -r requirements.txt

## Connection Handling

When operating in a load-balanced environment and using a load balancer (such as an Elastic Load Balancer) you will very likely have issues with TCP timeouts. ELBs in particular have hard-set timeout of 60 seconds, regardless of keep-alive activity. This script has a connection refresh time feature that will close and reopen a connection after a specified number of seconds. If you operate behind any kind of load balancer or have a firewall between your RabbitMQ server and log producer then you will almost certainly want to set the refresh value to just less then your TCP timeout threshold.

When a connection goes away an attempt will be made to reconnect immediately. Should this fail then any further incoming messages will be buffered inside the running process until the connection has been restored. This is a simple FIFO queue. Note that anything in the buffer will be processed prior to new messages upon reconnection to RabbitMQ.

## Sample Configuration

    [rabbitmq]
    host = localhost
    port = 5672
    queue = nginx

    # These must be either "True" or "False"
    durable = True
    auto_delete = False

    # 1: delete message on RabbitMQ restart
    # 2: persist to disk through RabbitMQ restarts
    delivery_mode = 2

    # Connection refreshes are necessary to handle TCP timeouts in some
    # environments that don't care about keep alives. EC2 has a hard-set 60 second
    # timeout on our Elastic Load Balancers, which is what forces the necessity
    # for the setting. Set to the number of seconds that must have elapsed for a
    # refresh to occur (make one second less then your timeout), or None to
    # disable (which sets the time interally to one year).
    refresh = 50

    # We can queue messages within the running worker if the broker is unavailable
    # and then release them when it comes back. This setting controls the maximum
    # number of *items* in the buffer, not the buffer memory size.
    buffer = 100000

    [logging]
    log_format = %%(asctime)s - %%(levelname)s - %%(message)s
    log_datefmt = %%m/%%d/%%Y %%I:%%M:%%S %%p

## Test Coverage

Our test coverage is pretty weak at the moment. It will need to be beefed-up considerably!

    root@dev:/vagrant/log-to-rabbitmq# nosetests --cover-erase --with-coverage --cover-package=log_to_rabbitmq -v tests.py
    Tests for proper handling of config elements ... ok
    Tests draining the queue buffer ... ok
    Tests the make_config function ... ok
    Tests that our AMQP class has names in it ... ok
    Tests that we can publish to the queue ... ok
    Tests the _refresh_connection method ... ok

    Name              Stmts   Miss  Cover   Missing
    -----------------------------------------------
    log_to_rabbitmq     155     59    62%   44, 93-95, 117, 149-151, 161-171, 225-289
    ----------------------------------------------------------------------
    Ran 6 tests in 0.135s

    OK


## License
log-to-rabbitmq is licensed under the MPLv2. If you have any questions regarding licensing,
please contact us at <info@honkmobile.com>.

