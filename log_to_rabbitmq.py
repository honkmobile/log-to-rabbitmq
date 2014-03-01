#!/usr/bin/env python

# ***** BEGIN LICENSE BLOCK *****
#
# For copyright and licensing please refer to COPYING.
#
# ***** END LICENSE BLOCK *****

"""
This script takes logs from stdin and publishes them to RabbitMQ. It is
especially useful for listening to a named pipe (e.g. in place of a web server
log file) and then forwarding to RabbitMQ before being processed by an
analytics engine.
"""

import argparse
import logging
import sys
import Queue
import time
import timeout_decorator
import traceback

from librabbitmq import Connection
from librabbitmq import ConnectionError
from ConfigParser import SafeConfigParser
from timeout_decorator import TimeoutError

__version__ = 0.1
__author__ = 'honkmobile'


class RabbitMQ(object):  # pylint: disable=r0903
    """Manages our queue connection"""

    __name__ = 'RabbitMQ'

    def __init__(self, config_parser):
        # Get our configs
        self.queue = config_parser.get('rabbitmq', 'queue')
        self.host = config_parser.get('rabbitmq', 'host')
        self.port = int(config_parser.get('rabbitmq', 'port'))
        self.delivery_mode = int(config_parser.get('rabbitmq',
                                                   'delivery_mode'))
        buffer_size = int(config_parser.get('rabbitmq', 'buffer'))
        if config_parser.get('rabbitmq', 'durable').lower() == 'true':
            self.durable = True
        else:
            self.durable = False
        if config_parser.get('rabbitmq', 'auto_delete').lower() == 'true':
            self.auto_delete = True
        else:
            self.auto_delete = False
        if config_parser.get('rabbitmq', 'refresh').lower() == 'none':
            self.refresh = int(time.time()) + 31536000
        else:
            self.refresh = int(config_parser.get('rabbitmq', 'refresh'))

        # This is a buffer to manage messages that come in while RabbitMQ may
        # be unavailable
        self.buffer = Queue.Queue(maxsize=buffer_size)

        # And set up our connection
        self.connection = None
        self.channel = None
        self.last_connect = 0
        self.processed_count = 0
        self._connect()
        self._declare()

    def __del__(self):
        self._close()

    def __unicode__(self):
        return self.__str__()

    def __str__(self):
        return __name__

    @timeout_decorator.timeout(5)
    def _connect(self):
        """Creates our AMQP connection"""
        try:
            self.connection = Connection(host=self.host)
            self.channel = self.connection.channel()
            logging.info('Connected to server')
            self.last_connect = int(time.time())
            return True
        except ConnectionError:
            logging.error('Unable to connect to server')
            return None

    def _close(self):
        """Closes the AMQP connection"""
        if self.connection is not None:
            self.connection.close()
        logging.debug('Closed connection')

    @timeout_decorator.timeout(5)
    def _declare(self):
        """Declares the queue used for receiving logs"""
        logging.debug('Declaring queue: ' + self.queue)
        try:
            self.channel.queue_declare(queue=self.queue,
                                       durable=self.durable,
                                       auto_delete=self.auto_delete)
            return True
        except AttributeError:
            # We raise here as faliing to declare the queue is an immediate
            # show-stopper that things cannot neatly recover from.
            raise

    def _refresh_connection(self):
        """
        This refreshes the AMQP connection after timeouts or DNS changes, which
        is an absolute must-have for load-balanced servers in an environment
        such as EC2 where the IP address of the host is not guaranteed to
        remain constant. RabbitMQ does not like network interruptions, so this
        is our attempt to handle them with a little bit of grace.
        """
        if int(time.time()) - self.last_connect > self.refresh:
            logging.info('Connection refresh threshold reached')
            self._close()
            result = self._connect()
            return result
        else:
            return True

    def publish(self, log, do_buffer=True):
        """
        Publishes a log entry into the queue. The do_buffer parameter is to
        prevent double-buffering of a log entry that may be caught elsewhere.
        """
        logging.debug('Publishing to ' + self.queue + ', message: ' + str(log))
        connection_result = self._refresh_connection()
        logging.debug('connection_result: ' + str(connection_result))
        if connection_result is None:
            logging.info('Buffering log message in publish')
            self.buffer.put(log)
            return True
        try:
            # Exchanges are not implemented (yet)
            self.channel.basic_publish(
                exchange='',
                routing_key=self.queue,
                body=log,
                delivery_mode=self.delivery_mode)
            self.processed_count = self.processed_count + 1
            return True
        except ConnectionError:
            # This may happen if the backend server has gone away. We call
            # _refresh_connection() to try and get it back. If this fails then
            # the message will be dropped. In the future it would be nice to
            # have an internal buffer for keeping these messages until the
            # queue comes back.
            logging.debug(
                'A ConnectionError was thrown when attempting to publish a ' +
                'message.')
            self.last_connect = 0
            raise


def drain_buffer(message_queue):
    """Attempts to drain all logs from the queue buffer, if there are any"""
    if not message_queue.buffer.empty():
        for log in range(message_queue.buffer.qsize()):
            logging.info(
                'Processing buffered message. ' +
                str(message_queue.buffer.qsize()) + ' message(s) remain')
            message_queue.publish(message_queue.buffer.get(), do_buffer=False)
        return True
    else:
        logging.debug('No messages buffered')
        return True

def make_config():
    """Generates a new sample config file and dumps it to stdout"""
    config = """[rabbitmq]
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
"""
    print(config)
    return True

if __name__ == '__main__':
    ARGPARSE = argparse.ArgumentParser(description='Take messages from stdin' +
                                       ' and feed them into RabbitMQ')
    ARGPARSE.add_argument('-c', '--config', nargs=1,
                          help='Path to config file', required=True)
    ARGPARSE.add_argument('-m', '--make-config', required=False, default=False,
                          action='store_true')
    ARGPARSE.add_argument('-l', '--log-level', required=False, default=30)
    ARGS = vars(ARGPARSE.parse_args())
    PARSER = SafeConfigParser()
    PARSER.read(ARGS['config'])
    logging.basicConfig(level=int(ARGS['log_level']),
                        format=PARSER.get('logging', 'log_format'),
                        datefmt=PARSER.get('logging', 'log_datefmt'))

    if ARGS['make_config'] is True:
        make_config()
        sys.exit(0)

    # We only instantiate our AMQP class *once*. After successfully connecting
    # and declaring our queue we then handle further connection issues within
    # the class itself. However, the queue declaration does need to succeed.
    try:
        QUEUE = RabbitMQ(PARSER)
    except ConnectionError:
        logging.fatal('Unable to create AMQP object')
        logging.fatal(traceback.format_exc())
        sys.exit(1)
    except AttributeError:
        # Can happen if we cannot declare our queue
        logging.fatal('Unable to declare our queue')
        logging.fatal(traceback.format_exc())
        sys.exit(1)
    except TimeoutError:
        logging.fatal('Timeout attempting to connect')
        logging.fatal(traceback.format_exc())
        sys.exit(1)

    # Our main loop that consumes emitted logs and pushes them into our queue
    while True:
        try:
            LINE = sys.stdin.readline().strip()
            if LINE:
                logging.debug('Received log: ' + LINE)
                try:
                    drain_buffer(QUEUE)
                    QUEUE.publish(LINE)
                except (TimeoutError, ConnectionError):
                    logging.error('Error attempting to publish message')
                    time.sleep(0.1)
                    logging.info('Buffering log message in __main__')
                    QUEUE.buffer.put(LINE)
            else:
                # This sleeping nonsense needs to be replaced with something
                # that is a but more graceful.
                time.sleep(0.1)
        except KeyboardInterrupt:
            logging.warning('Caught SIGINT, cleaning up')
            logging.info('Processed ' + str(QUEUE.processed_count) +
                         ' messages')
            if not QUEUE.buffer.empty():
                logging.warning('Objects remaining in the buffer: ' +
                                str(QUEUE.buffer.qsize()) + '. These will ' +
                                'be lost.')
            drain_buffer(QUEUE)
            break
