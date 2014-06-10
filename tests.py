#!/usr/bin/env python

# ***** BEGIN LICENSE BLOCK *****
#
# For copyright and licensing please refer to COPYING.
#
# ***** END LICENSE BLOCK *****

"""
These are test cases for the log_to_rabbitmq script. At present they have only
been run on Ubuuntu 12.10+ with Python 2.7, though they should work just fine
on any *NIX Python 2.7.

Python 3 cannot be supported until librabbitmq achieves this. When that happens
we'll have a party :)

If someone wants to make these tests work on other platforms (e.g. Windows,
Solaris) then we will be eternally grateful. However, we use UNIX signals, so
support on Windows would require some significant changes.

For now we run with this command:

nosetests --cover-erase --with-coverage --cover-package=log_to_rabbitmq \
tests.py

Test requirements:

    * properly configured log_to_rabbitmq.conf
    * working RabbitMQ server
    * modules from requirements.txt (e.g. pip install -r requirements.txt)

Obviously don't run this on a production system unless you do not care about
your data!
"""

import log_to_rabbitmq
import logging
import unittest
from ConfigParser import SafeConfigParser
from librabbitmq import ChannelError
from timeout_decorator import TimeoutError


class TestLogToRabbitMQ(unittest.TestCase):  # pylint: disable=r0904
    """Tests for the log-to-rabbitmq script"""

    def setUp(self):
        self.parser = SafeConfigParser()
        self.parser.read('log_to_rabbitmq.conf')

    def tearDown(self):
        del self.parser

    def test_name(self):
        """Tests that our AMQP class has names in it"""
        queue = log_to_rabbitmq.RabbitMQ(self.parser)
        assert queue.__name__
        assert queue.__unicode__()

    def test_config(self):
        """Tests for proper handling of config elements"""
        # This may pass a channel error if the queue has already been declared
        # durable. That's a totally acceptable result.
        try:
            self.parser.set('rabbitmq', 'durable', 'True')
            self.parser.set('rabbitmq', 'auto_delete', 'True')
            self.parser.set('rabbitmq', 'refresh', 'None')
            self.parser.set('rabbitmq', 'queue', 'unittest')
            queue = log_to_rabbitmq.RabbitMQ(self.parser)
            assert queue.publish('test message')
        except ChannelError:
            return True
        try:
            self.parser.set('rabbitmq', 'durable', 'False')
            self.parser.set('rabbitmq', 'auto_delete', 'False')
            self.parser.set('rabbitmq', 'refresh', '10')
            self.parser.set('rabbitmq', 'queue', 'unittest')
            queue = log_to_rabbitmq.RabbitMQ(self.parser)
            assert queue.publish('test message')
        except ChannelError:
            return True

    def test_refresh(self):
        """Tests the _refresh_connection method"""
        queue = log_to_rabbitmq.RabbitMQ(self.parser)
        queue.last_connect = 0
        assert queue._refresh_connection()  # pylint: disable=w0212

    def test_publish(self):
        """Tests that we can publish to the queue"""
        logging.debug('Using host: ' + self.parser.get('rabbitmq', 'host'))
        queue = log_to_rabbitmq.RabbitMQ(self.parser)
        assert queue.publish('test message')

    def test_drain_buffer(self):
        """Tests draining the queue buffer"""
        # We insert a message into the buffer here. Running the function twice
        # ensures it is fully drained.
        queue = log_to_rabbitmq.RabbitMQ(self.parser)
        queue.buffer.put('test message')
        assert log_to_rabbitmq.drain_buffer(queue)
        assert log_to_rabbitmq.drain_buffer(queue)

    def test_make_config(self):
        """Tests the make_config function"""
        assert log_to_rabbitmq.make_config()

    ##########################################################################
    # These tests do not work, unfortunately. Python's signal handling breaks
    # the coverage module.
    ##########################################################################

    # def test_cannot_connect(self):
    #     """Tests if the server is unavailable"""
    #     # Set our host to something that isn't a running RabbitMQ server
    #     self.parser.set('rabbitmq', 'host', 'example.com')
    #     with self.assertRaises(TimeoutError):
    #         queue = log_to_rabbitmq.RabbitMQ(self.parser)
    #         assert queue.publish('test message')
