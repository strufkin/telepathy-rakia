import calltest
import constants as cs
from servicetest import (
    EventPattern, call_async,
    assertEquals, assertNotEquals, assertContains, assertLength,
    assertDoesNotContain
    )

class DirectionChange(calltest.CallTest):

    def __init__(self, *params):
        self.sending = True
        self.receiving = True
        calltest.CallTest.__init__(self, *params)

    def stop_sending(self, content):

        self.sending = False

        content.stream.SetSending(False)
        self.q.expect('dbus-signal', signal='SendingStateChanged',
                      args=[cs.CALL_STREAM_FLOW_STATE_PENDING_STOP],
                      path=content.stream.__dbus_object_path__)

        content.stream.Media.CompleteSendingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STOPPED)

        o = self.q.expect_many(
            EventPattern('dbus-signal', signal='SendingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_STOPPED],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='LocalSendingStateChanged',
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))

        assertEquals(cs.CALL_SENDING_STATE_NONE, o[1].args[0])
        assertEquals(self.self_handle, o[1].args[1][0])
        reinvite_event = o[2]

        assertContains('a=recvonly', reinvite_event.sip_message.body)
        self.context.check_call_sdp(reinvite_event.sip_message.body)
        body = reinvite_event.sip_message.body.replace(
            'recvonly', self.receiving and 'sendonly' or 'inactive')
        
        self.context.accept(reinvite_event.sip_message, body)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        self.q.expect('sip-ack', cseq=ack_cseq)

    def start_sending(self, content):
        content.stream.SetSending(True)

        self.sending = True

        reinvite_event, lss = self.q.expect_many(
            EventPattern('sip-invite'),
            EventPattern('dbus-signal', signal='LocalSendingStateChanged',
                         path=content.stream.__dbus_object_path__))

        assertEquals(cs.CALL_SENDING_STATE_SENDING, lss.args[0])
        assertEquals(self.self_handle, lss.args[1][0])

        assertDoesNotContain('a=sendonly', reinvite_event.sip_message.body)
        if self.receiving:
            assertDoesNotContain('a=inactive',
                                 reinvite_event.sip_message.body)
            assertDoesNotContain('a=recvonly',
                                 reinvite_event.sip_message.body)
        else:
            assertContains('a=recvonly', reinvite_event.sip_message.body)


        self.context.check_call_sdp(reinvite_event.sip_message.body)
        self.context.accept(reinvite_event.sip_message)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        self.q.expect_many(
            EventPattern('sip-ack', cseq=ack_cseq),
            EventPattern('dbus-signal', signal='SendingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_PENDING_START]))

        content.stream.Media.CompleteSendingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STARTED)

        self.q.expect('dbus-signal', signal='SendingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_STARTED],
                         path=content.stream.__dbus_object_path__)

    def stop_start_sending_user_requested(self, content):
        self.stop_sending(content)
        self.start_sending(content)


    def stop_start_sending_remote_requested(self, content):
        lss_event = [
            EventPattern('dbus-signal', signal='LocalSendingStateChanged')]
        direction_events = [
            EventPattern('dbus-signal', signal='SendingStateChanged'),
            EventPattern('dbus-signal', signal='ReceivingStateChanged'),
        ]

        self.stop_sending(content)
        self.q.forbid_events(lss_event)
        self.q.forbid_events(direction_events)

        self.context.reinvite([('audio','sendonly')])

        acc = self.q.expect('sip-response', call_id=self.context.call_id,
                            code=200)
        assertContains('a=recvonly', acc.sip_message.body)

        self.context.check_call_sdp(acc.sip_message.body)
        self.context.ack(acc.sip_message)

        self.q.unforbid_events(lss_event)

        self.context.reinvite([('audio','')])

        acc, lss = self.q.expect_many(
            EventPattern('sip-response', call_id=self.context.call_id,
                         code=200),
            EventPattern('dbus-signal', signal='LocalSendingStateChanged'))
        assertEquals(cs.CALL_SENDING_STATE_PENDING_SEND, lss.args[0])
        assertEquals(self.remote_handle, lss.args[1][0])
        assertContains('a=recvonly', acc.sip_message.body)

        assertEquals(cs.CALL_STREAM_FLOW_STATE_STOPPED,
                     content.stream.Properties.Get(cs.CALL_STREAM_IFACE_MEDIA,
                                                   'SendingState'))

        self.context.check_call_sdp(acc.sip_message.body)
        self.context.ack(acc.sip_message)
                    
        self.q.unforbid_events(direction_events)
        self.start_sending(content)

    def reject_stop_receiving(self, content):
        content.stream.RequestReceiving(self.remote_handle, False)


        o = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_PENDING_STOP],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))


        assertLength(0, o[1].args[2])
        assertLength(1, o[1].args[0])
        assertEquals(cs.CALL_SENDING_STATE_PENDING_STOP_SENDING,
                     o[1].args[0][self.remote_handle])
        assertEquals(self.self_handle, o[1].args[3][0])
        assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])
        reinvite_event = o[2]

        assertContains('a=sendonly', reinvite_event.sip_message.body)
        self.context.check_call_sdp(reinvite_event.sip_message.body)
        if self.sending:
            body = reinvite_event.sip_message.body.replace('sendonly',
                                                           'sendrecv')
        
        self.context.accept(reinvite_event.sip_message, body)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        self.q.expect('sip-ack', cseq=ack_cseq)

        # Return to regular state

        invite_event = [EventPattern('sip-invite')]

        self.q.forbid_events(invite_event)

        content.stream.RequestReceiving(self.remote_handle, True)

        _ , o = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_PENDING_START],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__,
                         predicate=lambda e: self.remote_handle in e.args[0] and e.args[0][self.remote_handle] == cs.CALL_SENDING_STATE_PENDING_SEND))

        assertLength(1, o.args[0])
        assertLength(0, o.args[2])
        assertEquals(cs.CALL_SENDING_STATE_PENDING_SEND,
                     o.args[0][self.remote_handle])
        assertEquals(self.self_handle, o.args[3][0])
        assertEquals(cs.CALL_SCR_USER_REQUESTED, o.args[3][1])
        
        self.context.options_ping(self.q)
        self.q.unforbid_events(invite_event)

        content.stream.Media.CompleteReceivingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STARTED)

        _, reinvite_event = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_STARTED],
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))

        assertDoesNotContain('a=sendonly', reinvite_event.sip_message.body)
        assertDoesNotContain('a=recvonly', reinvite_event.sip_message.body)
        assertDoesNotContain('a=inactive', reinvite_event.sip_message.body)
        self.context.check_call_sdp(reinvite_event.sip_message.body)
        self.context.accept(reinvite_event.sip_message)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        o = self.q.expect_many(
            EventPattern('sip-ack', cseq=ack_cseq),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__))

        assertLength(0, o[1].args[2])
        assertLength(1, o[1].args[0])
        assertEquals(cs.CALL_SENDING_STATE_SENDING,
                     o[1].args[0][self.remote_handle])




    def stop_receiving(self, content):
        self.receiving = False

        content.stream.RequestReceiving(self.remote_handle, False)

        o = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_PENDING_STOP],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))


        assertLength(0, o[1].args[2])
        assertLength(1, o[1].args[0])
        assertEquals(cs.CALL_SENDING_STATE_PENDING_STOP_SENDING,
                     o[1].args[0][self.remote_handle])
        assertEquals(self.self_handle, o[1].args[3][0])
        assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])
        reinvite_event = o[2]

        assertContains('a=sendonly', reinvite_event.sip_message.body)
        self.context.check_call_sdp(reinvite_event.sip_message.body)
        body = reinvite_event.sip_message.body.replace(
            'sendonly', self.sending and 'recvonly' or 'inactive')
        
        self.context.accept(reinvite_event.sip_message, body)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        o = self.q.expect_many(
            EventPattern('sip-ack', cseq=ack_cseq),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__))

        assertLength(1, o[1].args[0])
        assertLength(0, o[1].args[2])
        assertEquals(cs.CALL_SENDING_STATE_NONE,
                     o[1].args[0][self.remote_handle])
        #assertEquals(self.remote_handle, o[1].args[3][0])
        #assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])
        
        content.stream.Media.CompleteReceivingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STOPPED)

        self.q.expect('dbus-signal', signal='ReceivingStateChanged',
                      args=[cs.CALL_STREAM_FLOW_STATE_STOPPED],
                      path=content.stream.__dbus_object_path__),

    def start_receiving(self, content):
        self.receiving = True

        content.stream.RequestReceiving(self.remote_handle, True)

        self.q.expect('dbus-signal', signal='ReceivingStateChanged',
                 args=[cs.CALL_STREAM_FLOW_STATE_PENDING_START],
                 path=content.stream.__dbus_object_path__),

        content.stream.Media.CompleteReceivingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STARTED)

        o = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_STARTED],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))


        assertLength(0, o[1].args[2])
        assertLength(1, o[1].args[0])
        assertEquals(cs.CALL_SENDING_STATE_PENDING_SEND,
                     o[1].args[0][self.remote_handle])
        assertEquals(self.self_handle, o[1].args[3][0])
        assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])
        reinvite_event = o[2]

        assertDoesNotContain('a=sendonly', reinvite_event.sip_message.body)
        assertDoesNotContain('a=inactive', reinvite_event.sip_message.body)
        self.context.check_call_sdp(reinvite_event.sip_message.body)
        
        self.context.accept(reinvite_event.sip_message)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        o = self.q.expect_many(
            EventPattern('sip-ack', cseq=ack_cseq),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__))

        assertLength(1, o[1].args[0])
        assertLength(0, o[1].args[2])
        assertEquals(cs.CALL_SENDING_STATE_SENDING,
                     o[1].args[0][self.remote_handle])
        #assertEquals(self.remote_handle, o[1].args[3][0])
        #assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])


    def stop_start_receiving_user_requested(self, content):
        self.stop_receiving(content)
        self.start_receiving(content)

    def reject_start_receiving(self, content):
        self.stop_receiving(content)

        content.stream.RequestReceiving(self.remote_handle, True)

        self.q.expect('dbus-signal', signal='ReceivingStateChanged',
                 args=[cs.CALL_STREAM_FLOW_STATE_PENDING_START],
                 path=content.stream.__dbus_object_path__),

        content.stream.Media.CompleteReceivingStateChange(
            cs.CALL_STREAM_FLOW_STATE_STARTED)

        o = self.q.expect_many(
            EventPattern('dbus-signal', signal='ReceivingStateChanged',
                         args=[cs.CALL_STREAM_FLOW_STATE_STARTED],
                         path=content.stream.__dbus_object_path__),
            EventPattern('dbus-signal', signal='RemoteMembersChanged',
                         path=content.stream.__dbus_object_path__),
            EventPattern('sip-invite'))


        assertLength(0, o[1].args[2])
        assertLength(1, o[1].args[0])
        assertEquals(cs.CALL_SENDING_STATE_PENDING_SEND,
                     o[1].args[0][self.remote_handle])
        assertEquals(self.self_handle, o[1].args[3][0])
        assertEquals(cs.CALL_SCR_USER_REQUESTED, o[1].args[3][1])
        reinvite_event = o[2]

        assertDoesNotContain('a=sendonly', reinvite_event.sip_message.body)
        assertDoesNotContain('a=inactive', reinvite_event.sip_message.body)

        self.context.check_call_sdp(reinvite_event.sip_message.body)
        body = reinvite_event.sip_message.body + 'a=sendonly\r\r'
        self.context.accept(reinvite_event.sip_message, body)

        ack_cseq = "%s ACK" % reinvite_event.cseq.split()[0]
        self.q.expect('sip-ack', cseq=ack_cseq)

        

    def during_call(self):
        content = self.contents[0]

        remote_hold_event = [
            EventPattern('dbus-signal', signal='CallStateChanged')]
        self.q.forbid_events(remote_hold_event)

        self.stop_start_sending_user_requested(content)
        self.stop_start_sending_remote_requested(content)

        self.stop_start_receiving_user_requested(content)

        self.reject_stop_receiving(content)
        self.stop_start_receiving_user_requested(content)
        self.reject_start_receiving(content)

        self.q.unforbid_events(remote_hold_event)
        return calltest.CallTest.during_call(self)




if __name__ == '__main__':
    calltest.run(klass=DirectionChange)
    
