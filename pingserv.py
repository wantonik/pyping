#!/usr/bin/env python

# Copyright 2001, The Institute for Open Systems Technologies
# written by Greg Baker  <greg.baker@ifost.org.au>

"""Ping. Round-trip delay measurement utility.

Uses ICMP ECHO_REQEST messages to measure the delay between two
Internet hosts.

This version implements parallel pinging (single threaded,  using
select) to implement the beginnings of HP OpenView netmon functionality
"""

import icmp, ip, ping
import socket
import time
import select
import string
import os, sys
import asyncore

TimedOut = 'TimedOut'

NonBlockingPingerRegistry = {}

def nearest_future_event_time():
   nearest_future = sys.maxint  # sometime in 2038 for 32-bit computers
   for pinger in NonBlockingPingerRegistry.values():
       when = pinger.expiry_time()
       if (nearest_future > when):  nearest_future = when
   return nearest_future

def custom_select(rd,wr,er,timeout=None,also_asyncore=1):
   """selects on all NonBlockingPingers,  and any rd you specify;
   you can have wr and er as well.  It will check when the next event
   is due;  if your timeout is closer in the future than that,  it will
   get used,  otherwise ignored.  timeout is optional. If also_asyncore
   is set (as it defaults to),  it will also pick up on any sockets in
   asyncore.socket_map"""
   known_timeout = nearest_future_event_time() - time.time()
   if known_timeout < timeout: timeout = known_timeout
   asr = []; asw = []; ase = []
   if (also_asyncore == 1):
       for s in asyncore.socket_map.keys():
	   if s.readable():  asr.append(s)
	   if s.writable():  asw.append(s)
   (rdrs,wrtrs,errs) = select.select(rd+NonBlockingPingerRegistry.keys()+asr,wr+asw,er+ase,timeout)
   other_rdrs = []
   for r in rdrs:
       if NonBlockingPingerRegistry.has_key(r):
          NonBlockingPingerRegistry[r].read_received_response()
       elif asyncore.socket_map.has_key(r):
	  try: 
	      r.handle_read_event()
	  except:
	      r.handle_error()
       else:
          other_rdrs.append(r)
   other_wrtrs = []
   for w in wrtrs:
       if asyncore.socket_map.has_key(w):
	   try:
	       w.handle_write_event()
	   except:
	       w.handle_error()
       else:
	   other_wrtrs.append(w)
   return (other_rdrs,other_wrtrs,errs)

def triage():
   """returns the living and the dead (in that order),  and updates the
   registry"""
   now = time.time()
   dead = []
   living = []
   for pinger in NonBlockingPingerRegistry.values():
       if pinger.has_expired(now):
          dead.append(pinger)
          del NonBlockingPingerRegistry[pinger.sock.socket.fileno()]
       if pinger.got_response == 1:
          living.append(pinger)
          del NonBlockingPingerRegistry[pinger.sock.socket.fileno()]
   return (living,dead)

class NonBlockingPinger(ping.Pinger):
    def __init__(self, addr, respond_within):
        ping.Pinger.__init__(self,addr,1)
        NonBlockingPingerRegistry[self.sock.socket.fileno()] = self
        self.respond_within = respond_within
        self.sock.socket.setblocking(0)
        self.got_response = 0
	self.received_garbage = 0

    def expiry_time(self):
        if self.times.has_key(0):
           return self.respond_within + self.times[0]
        else:
           raise IndexError,"self.send_packet has not yet run -- how do I know when it will expire?"

    def has_expired(self,when=None):
        if self.got_response == 1: return 0
        if when is None: when = time.time()
        return self.expiry_time() > when

    def status(self):
        "1 means alive,  0 means still waiting, -1 means dead"
        if self.got_response == 1: return 1
	if self.received_garbage == 1: return -1
        if self.has_expired(): return -1
        return 0

    def recv_output(self, bytes, dest, addr, seq, delta):
	"Place holder for subclass output/collector method"
	pass

    def ping(self):
        raise ValueError,"Can't use ping() method in a NonBlockingPinger"

    def read_received_response(self):
        """When you've selected on NonBlockingPingerRegistry.keys(), you
        will get a list back;  iterate i over each element and call
        this NonBlockingPingerRegistry[i].read_received_response()"""
	try:
	    pkt, who = self.sock.recvfrom(4096)
	except socket.error:
            raise ValueError,"There was no data on that socket"
	# could also use the ip module to get the payload
	repip = ip.Packet(pkt)
	try:
	    reply = icmp.Packet(repip.data)
	except:
	    self.received_garbage = 1
	    return
	if reply.id == self.pid:
            arrival = time.time()
	    self.recv_packet(reply, arrival)
	    self.last_arrival = arrival
            self.got_response = 1

if __name__ == "__main__":
    if sys.argv[1:] != []:
	for hostname in sys.argv[1:]:
	    NonBlockingPinger(hostname,1.0).send_packet()
	while NonBlockingPingerRegistry.keys() != []:
	    (rdrs,wrtrs,xrrs) = custom_select([],[],[])
	    (living,dead) = triage()
	    for alive in living: print alive.addr,"is alive"
	    for lost in dead: print lost.addr,"is unreachable"
    else:
	pass


