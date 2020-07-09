import time;

try: # mDebugOutput use is Optional
  from mDebugOutput import *;
except: # Do nothing if not available.
  ShowDebugOutput = lambda fxFunction: fxFunction;
  fShowDebugOutput = lambda sMessage: None;
  fEnableDebugOutputForModule = lambda mModule: None;
  fEnableDebugOutputForClass = lambda cClass: None;
  fEnableAllDebugOutput = lambda: None;
  cCallStack = fTerminateWithException = fTerminateWithConsoleOutput = None;

from .mExceptions import *;
from .cHTTPConnection import cHTTPConnection;

from mMultiThreading import cLock, cWithCallbacks;

# To turn access to data store in multiple variables into a single transaction, we will create locks.
# These locks should only ever be locked for a short time; if it is locked for too long, it is considered a "deadlock"
# bug, where "too long" is defined by the following value:
gnDeadlockTimeoutInSeconds = 1; # We're not doing anything time consuming, so this should suffice.
guzDefaultMaxNumerOfConnectionsToServer = 10;

class cHTTPConnectionsToServerPool(cWithCallbacks):
  @ShowDebugOutput
  def __init__(oSelf,
    oServerBaseURL,
    uzMaxNumerOfConnectionsToServer = None,
    ozSSLContext = None
  ):
    oSelf.__oServerBaseURL = oServerBaseURL;
    oSelf.__uzMaxNumerOfConnectionsToServer = uzMaxNumerOfConnectionsToServer if uzMaxNumerOfConnectionsToServer is not None else guzDefaultMaxNumerOfConnectionsToServer;
    oSelf.__ozSSLContext = ozSSLContext;
    
    oSelf.__oConnectionsPropertyLock = cLock(
      "%s.__oConnectionsPropertyLock" % oSelf.__class__.__name__,
      nzDeadlockTimeoutInSeconds = gnDeadlockTimeoutInSeconds
    );
    oSelf.__aoConnections = [];
    oSelf.__uPendingConnects = 0;
    
    oSelf.__bStopping = False;
    oSelf.__oTerminatedPropertyLock = cLock(
      "%s.__oTerminatedEventFiredLock" % oSelf.__class__.__name__,
      nzDeadlockTimeoutInSeconds = gnDeadlockTimeoutInSeconds
    );
    oSelf.__oTerminatedLock = cLock(
      "%s.__oTerminatedLock" % oSelf.__class__.__name__,
      bLocked = True
    );
    
    oSelf.fAddEvents(
      "connect failed",
      "new connection",
      "request sent", "response received",
      "request sent and response received",
      "connection terminated",
      "terminated"
    );
  
  @property
  def bTerminated(oSelf):
    return not oSelf.__oTerminatedLock.bLocked;
  
  @property
  def uConnectionsCount(oSelf):
    return len(oSelf.__aoConnections);
  
  @property
  def aoConnections(oSelf):
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      return oSelf.__aoConnections[:];
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
  
  @ShowDebugOutput
  def __fCheckIfTerminated(oSelf):
    assert oSelf.__bStopping, \
        "This functions should not be called if we are not stopping!";
    assert not oSelf.__aoConnections, \
        "This functions should not be called if there are active connections!";
    oSelf.__oTerminatedPropertyLock.fAcquire();
    try:
      if oSelf.bTerminated: return;
      oSelf.__oTerminatedLock.fRelease();
    finally:
      oSelf.__oTerminatedPropertyLock.fRelease();
    fShowDebugOutput("cHTTPConnectionsToServerPool terminated.");
    oSelf.fFireCallbacks("terminated");
  
  @ShowDebugOutput
  def fStop(oSelf):
    if oSelf.bTerminated:
      return fShowDebugOutput("Already terminated");
    if oSelf.__bStopping:
      return fShowDebugOutput("Already stopping");
    fShowDebugOutput("Stopping...");
    oSelf.__bStopping = True;
    # Tell all connections to stop
    aoConnections = oSelf.aoConnections;
    if aoConnections:
      # If there are connections, stop them.
      for oConnection in aoConnections:
        oConnection.fStop();
    else:
      # Otherwise we may have just terminated.
      oSelf.__fCheckIfTerminated();
    return
  
  @ShowDebugOutput
  def fTerminate(oSelf):
    oSelf.__bStopping = True;
    aoConnections = oSelf.aoConnections;
    if aoConnections:
      # If there are connections, terminate them.
      for oConnection in aoConnections:
        oConnection.fTerminate();
    else:
      # Otherwise we may have just terminated.
      oSelf.__fCheckIfTerminated();
  
  @ShowDebugOutput
  def fbWait(oSelf, bTimeoutInSeconds):
    return oSelf.__oTerminatedLock.fbWait(bTimeoutInSeconds);
  
  @ShowDebugOutput
  def fozSendRequestAndReceiveResponse(oSelf,
    oRequest,
    nzConnectTimeoutInSeconds = None, nzSecureTimeoutInSeconds = None, nzTransactionTimeoutInSeconds = None,
    bEndTransaction = True,
    uzMaximumNumberOfChunksBeforeDisconnecting = None, # disconnect and return response once this many chunks are received.
  ):
    # Send a request to the server and receive a response.
    # An existing connection is reused if one is available. A new connection
    # if created if none is available and there are not too many connections.
    # If not specified, always check the hostname when the connection is secure.
    # Can throw a max-connections-reached exception
    if oSelf.__bStopping:
      return None;
    # Returns cResponse instance if response was received.
    fShowDebugOutput("Getting connection...");
    oConnection = oSelf.__foStartTransactionOnExistingConnection(nzTransactionTimeoutInSeconds);
    if oConnection is None:
      if oSelf.__bStopping:
        return None;
      oConnection = oSelf.__foCreateNewConnectionAndStartTransaction(
        nzConnectTimeoutInSeconds, nzSecureTimeoutInSeconds, nzTransactionTimeoutInSeconds
      );
      if oSelf.__bStopping:
        return None;
      assert oConnection, \
          "A new connection was not established even though we are not stopping!?";
    oResponse = oConnection.fozSendRequestAndReceiveResponse(
      oRequest,
      bStartTransaction = False,
      uzMaximumNumberOfChunksBeforeDisconnecting = uzMaximumNumberOfChunksBeforeDisconnecting, # disconnect and return response once this many chunks are received.
      bEndTransaction = bEndTransaction,
    );
    if oSelf.__bStopping:
      fShowDebugOutput("Stopping.");
      return None;
    assert oResponse, \
        "Expected a response but got %s" % repr(oResponse);
    oSelf.fFireCallbacks("request sent and response received", oConnection, oRequest, oResponse);
    return oResponse;
  
  @ShowDebugOutput
  def __foStartTransactionOnExistingConnection(oSelf, nzTransactionTimeoutInSeconds):
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      for oConnection in oSelf.__aoConnections:
        if oSelf.__bStopping:
          return None;
        if oConnection.fbStartTransaction(nzTransactionTimeoutInSeconds):
          return oConnection;
      return None;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
  
  @ShowDebugOutput
  def __foCreateNewConnectionAndStartTransaction(oSelf,
    nzConnectTimeoutInSeconds, nzSecureTimeoutInSeconds, nzTransactionTimeoutInSeconds
  ):
    # Make sure we would not create too many connections and add a pending connection:
    # Can throw a max-connections-reached exception
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      if len(oSelf.__aoConnections) + oSelf.__uPendingConnects == oSelf.__uzMaxNumerOfConnectionsToServer:
        raise cMaxConnectionsReachedException(
          "Cannot create more connections to the server",
          {"uMaxNumerOfConnectionsToServer": oSelf.__uzMaxNumerOfConnectionsToServer}
        );
      oSelf.__uPendingConnects += 1;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    # Try to establish a connection:
    oConnection = None;
    try:
      oConnection = cHTTPConnection.foConnectTo(
        sHostname = oSelf.__oServerBaseURL.sHostname,
        uPort = oSelf.__oServerBaseURL.uPort,
        nzConnectTimeoutInSeconds = nzConnectTimeoutInSeconds,
        ozSSLContext = oSelf.__ozSSLContext,
        nzSecureTimeoutInSeconds = nzSecureTimeoutInSeconds,
      );
    except Exception as oException:
      oSelf.fFireCallbacks("connect failed", oSelf.__oServerBaseURL.sHostname, oSelf.__oServerBaseURL.uPort, oException);
      raise;
    else:
      # Start a transaction to prevent other threads from using it:
      assert oConnection.fbStartTransaction(nzTransactionTimeoutInSeconds), \
           "Cannot start a transaction on a new connection (%s)" % repr(oConnection);
    finally:
      # remove a pending connection and add it if it was successfuly created.
      oSelf.__oConnectionsPropertyLock.fAcquire();
      try:
        oSelf.__uPendingConnects -= 1;
        if oConnection:
          oSelf.__aoConnections.append(oConnection);
      finally:
        oSelf.__oConnectionsPropertyLock.fRelease();
    # Add some 
    oConnection.fAddCallback("request sent", oSelf.__fHandleRequestSentCallbackFromConnection);
    oConnection.fAddCallback("response received", oSelf.__fHandleResponseReceivedCallbackFromConnection);
    oConnection.fAddCallback("terminated", oSelf.__fHandleTerminatedCallbackFromConnection);
    oSelf.fFireCallbacks("new connection", oConnection);
    return oConnection;
  
  def __fHandleRequestSentCallbackFromConnection(oSelf, oConnection, oRequest):
    oSelf.fFireCallbacks("request sent", oConnection, oRequest);
  
  def __fHandleResponseReceivedCallbackFromConnection(oSelf, oConnection, oResponse):
    oSelf.fFireCallbacks("response received", oConnection, oResponse);
  
  @ShowDebugOutput
  def __fHandleTerminatedCallbackFromConnection(oSelf, oConnection):
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__aoConnections.remove(oConnection);
      bCheckIfTerminated = oSelf.__bStopping and len(oSelf.__aoConnections) == 0;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    oSelf.fFireCallbacks("connection terminated", oConnection);
    if bCheckIfTerminated:
      oSelf.__fCheckIfTerminated();
  
  def fasGetDetails(oSelf):
    uConnectionsCount = oSelf.uConnectionsCount;
    bTerminated = oSelf.bTerminated;
    return [s for s in [
      oSelf.__oServerBaseURL.sBase,
      "%d connections" % uConnectionsCount if not bTerminated else None,
      "secure" if oSelf.__ozSSLContext else None,
      "terminated" if bTerminated else
          "stopping" if oSelf.__bStopping else None,
    ] if s];
  
  def __repr__(oSelf):
    sModuleName = ".".join(oSelf.__class__.__module__.split(".")[:-1]);
    return "<%s.%s#%X|%s>" % (sModuleName, oSelf.__class__.__name__, id(oSelf), "|".join(oSelf.fasGetDetails()));
  
  def __str__(oSelf):
    return "%s#%X{%s}" % (oSelf.__class__.__name__, id(oSelf), ", ".join(oSelf.fasGetDetails()));
