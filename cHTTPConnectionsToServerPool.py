import time;

try: # mDebugOutput use is Optional
  from mDebugOutput import ShowDebugOutput, fShowDebugOutput;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mDebugOutput'":
    raise;
  ShowDebugOutput = fShowDebugOutput = lambda x: x; # NOP

from mMultiThreading import cLock, cWithCallbacks;
from mNotProvided import *;

from .cHTTPConnection import cHTTPConnection;
from .mExceptions import *;

# To turn access to data store in multiple variables into a single transaction, we will create locks.
# These locks should only ever be locked for a short time; if it is locked for too long, it is considered a "deadlock"
# bug, where "too long" is defined by the following value:
gnDeadlockTimeoutInSeconds = 1; # We're not doing anything time consuming, so this should suffice.
gu0DefaultMaxNumberOfConnectionsToServer = 10;

class cHTTPConnectionsToServerPool(cWithCallbacks):
  @ShowDebugOutput
  def __init__(oSelf,
    oServerBaseURL,
    u0zMaxNumberOfConnectionsToServer = zNotProvided,
    o0SSLContext = None
  ):
    oSelf.__oServerBaseURL = oServerBaseURL;
    oSelf.__u0MaxNumberOfConnectionsToServer = fxGetFirstProvidedValue(u0zMaxNumberOfConnectionsToServer, gu0DefaultMaxNumberOfConnectionsToServer);
    oSelf.__o0SSLContext = o0SSLContext;
    
    oSelf.__oConnectionsPropertyLock = cLock(
      "%s.__oConnectionsPropertyLock" % oSelf.__class__.__name__,
      n0DeadlockTimeoutInSeconds = gnDeadlockTimeoutInSeconds
    );
    oSelf.__aoConnections = []; # The connections this pool can use itself
    oSelf.__aoExternalizedConnections = []; # The connections this pool has provided for use by others.
    oSelf.__uPendingConnects = 0;
    
    oSelf.__bStopping = False;
    oSelf.__oTerminatedPropertyLock = cLock(
      "%s.__oTerminatedEventFiredLock" % oSelf.__class__.__name__,
      n0DeadlockTimeoutInSeconds = gnDeadlockTimeoutInSeconds
    );
    oSelf.__oTerminatedLock = cLock(
      "%s.__oTerminatedLock" % oSelf.__class__.__name__,
      bLocked = True
    );
    
    oSelf.fAddEvents(
      "hostname resolved",
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
    return len(oSelf.__aoConnections) + len(oSelf.__aoExternalizedConnections);
  
#  @property
#  def aoConnections(oSelf):
#    oSelf.__oConnectionsPropertyLock.fAcquire();
#    try:
#      return oSelf.__aoConnections[:];
#    finally:
#      oSelf.__oConnectionsPropertyLock.fRelease();
  
  @ShowDebugOutput
  def __fReportTerminatedIfNoMoreConnectionsExist(oSelf):
    assert oSelf.__bStopping, \
        "This functions should not be called if we are not stopping!";
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      if oSelf.__aoConnections or oSelf.__aoExternalizedConnections:
        # There are existing connections; termination will be reported when
        # they all terminate too.
        return;
      oSelf.__oTerminatedPropertyLock.fAcquire();
      try:
        if not oSelf.__oTerminatedLock.bLocked: return; # Already terminated
        # Yes, we have terminated and must release the lock
        # and fire events.
        oSelf.__oTerminatedLock.fRelease();
      finally:
        oSelf.__oTerminatedPropertyLock.fRelease();
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
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
    # We are now officially stopping, so there should not be any new connections
    # added from this point onward.  If there are existing connections, we will
    # stop them:
    for oConnection in oSelf.__aoConnections[:]:
      oConnection.fStop();
    # If there are no connections and we have not terminated, do so now:
    oSelf.__fReportTerminatedIfNoMoreConnectionsExist();
  
  @ShowDebugOutput
  def fTerminate(oSelf):
    if oSelf.bTerminated:
      return fShowDebugOutput("Already terminated");
    fShowDebugOutput("Terminated...");
    oSelf.__bStopping = True;
    # We are now officially stopping, so there should not be any new connections
    # added from this point onward.  If there are existing connections, we will
    # terminate them:
    for oConnection in oSelf.__aoConnections[:]:
      oConnection.fTerminate();
    # If there are no connections and we have not terminated, do so now:
    oSelf.__fReportTerminatedIfNoMoreConnectionsExist();
  
  @ShowDebugOutput
  def fbWait(oSelf, bTimeoutInSeconds):
    return oSelf.__oTerminatedLock.fbWait(bTimeoutInSeconds);
  
  def fo0GetConnectionAndStartTransaction(
    oSelf,
    n0zConnectTimeoutInSeconds = zNotProvided,
    bSecure = True,
    n0zSecureTimeoutInSeconds = zNotProvided,
    n0zTransactionTimeoutInSeconds = zNotProvided,
  ):
    # Wrapper for the internal version. This external version also marks the
    # connection as having been passed externally, to prevent it from being
    # used as part of the regular pool. The caller is responsible for closing
    # the connection.
    o0Connection = oSelf.__fo0GetConnectionAndStartTransaction(
      n0zConnectTimeoutInSeconds,
      bSecure,
      n0zSecureTimeoutInSeconds,
      n0zTransactionTimeoutInSeconds,
    );
    if o0Connection is None:
      return None;
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__aoConnections.remove(o0Connection);
      oSelf.__aoExternalizedConnections.append(o0Connection);
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    return o0Connection;
  
  def __fo0GetConnectionAndStartTransaction(
    oSelf,
    n0zConnectTimeoutInSeconds,
    bSecure,
    n0zSecureTimeoutInSeconds,
    n0zTransactionTimeoutInSeconds,
  ):
    if oSelf.__bStopping:
      return None;
    fShowDebugOutput("Getting connection...");
    if bSecure:
      # Secure connections may already exist and can be reused:
      o0Connection = oSelf.__fo0StartTransactionOnExistingConnection(n0zTransactionTimeoutInSeconds);
      if o0Connection is not None:
        return o0Connection;
      if oSelf.__bStopping:
        return None;
    oConnection = oSelf.__foCreateNewConnectionAndStartTransaction(
      n0zConnectTimeoutInSeconds,
      bSecure,
      n0zSecureTimeoutInSeconds,
      n0zTransactionTimeoutInSeconds,
    );
    if oSelf.__bStopping:
      return None;
    assert oConnection, \
        "A new connection was not established even though we are not stopping!?";
    return oConnection;
  
  @ShowDebugOutput
  def fo0SendRequestAndReceiveResponse(oSelf,
    oRequest,
    n0zConnectTimeoutInSeconds = zNotProvided, n0zSecureTimeoutInSeconds = zNotProvided, n0zTransactionTimeoutInSeconds = zNotProvided,
    bEndTransaction = True,
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided, u0zMaxHeaderValueSize = zNotProvided, u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided, u0zMaxChunkSize = zNotProvided, u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = zNotProvided, # disconnect and return response once this many chunks are received.
  ):
    # Send a request to the server and receive a response.
    # An existing connection is reused if one is available. A new connection
    # if created if none is available and there are not too many connections.
    # If not specified, always check the hostname when the connection is secure.
    # Can throw a max-connections-reached exception
    if oSelf.__bStopping:
      return None;
    oConnection = oSelf.__fo0GetConnectionAndStartTransaction(
      n0zConnectTimeoutInSeconds = n0zConnectTimeoutInSeconds,
      bSecure = True,
      n0zSecureTimeoutInSeconds = n0zSecureTimeoutInSeconds,
      n0zTransactionTimeoutInSeconds = n0zTransactionTimeoutInSeconds,
    );
    # oConnection can be None only if we are stopping.
    if oSelf.__bStopping:
      return None;
    assert oConnection, \
        "A new connection was not established even though we are not stopping!?";
    # Returns cResponse instance if response was received.
    oResponse = oConnection.fo0SendRequestAndReceiveResponse(
      oRequest,
      bStartTransaction = False,
      u0zMaxStatusLineSize = u0zMaxStatusLineSize,
      u0zMaxHeaderNameSize = u0zMaxHeaderNameSize,
      u0zMaxHeaderValueSize = u0zMaxHeaderValueSize,
      u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
      u0zMaxBodySize = u0zMaxBodySize,
      u0zMaxChunkSize = u0zMaxChunkSize,
      u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
      u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting, # disconnect and return response once this many chunks are received.
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
  def __fo0StartTransactionOnExistingConnection(oSelf, n0zTransactionTimeoutInSeconds):
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      for oConnection in oSelf.__aoConnections:
        if oSelf.__bStopping:
          return None;
        if oConnection.fbStartTransaction(n0zTransactionTimeoutInSeconds):
          return oConnection;
      return None;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
  
  @ShowDebugOutput
  def __foCreateNewConnectionAndStartTransaction(oSelf,
    n0zConnectTimeoutInSeconds,
    bSecure,
    n0zSecureTimeoutInSeconds,
    n0zTransactionTimeoutInSeconds
  ):
    # Make sure we would not create too many connections and add a pending connection:
    # Can throw a max-connections-reached exception
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      if (
        oSelf.__u0MaxNumberOfConnectionsToServer is not None
        and len(oSelf.__aoConnections) + oSelf.__uPendingConnects == oSelf.__u0MaxNumberOfConnectionsToServer
      ):
        raise cMaxConnectionsReachedException(
          "Cannot create more connections to the server",
          {"uMaxNumberOfConnectionsToServer": oSelf.__u0MaxNumberOfConnectionsToServer}
        );
      oSelf.__uPendingConnects += 1;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    # Try to establish a connection:
    try:
      oConnection = cHTTPConnection.foConnectTo(
        sbHostname = oSelf.__oServerBaseURL.sbHostname,
        uPortNumber = oSelf.__oServerBaseURL.uPortNumber,
        n0zConnectTimeoutInSeconds = n0zConnectTimeoutInSeconds,
        o0SSLContext = oSelf.__o0SSLContext if bSecure else None,
        n0zSecureTimeoutInSeconds = n0zSecureTimeoutInSeconds,
        f0ResolveHostnameCallback = oSelf.__fHandleResolveHostnameCallback
      );
    except Exception as oException:
      oSelf.fFireCallbacks("connect failed", oSelf.__oServerBaseURL.sbHostname, oSelf.__oServerBaseURL.uPortNumber, oException);
      # remove a pending connection.
      oSelf.__oConnectionsPropertyLock.fAcquire();
      try:
        oSelf.__uPendingConnects -= 1;
      finally:
        oSelf.__oConnectionsPropertyLock.fRelease();
      raise;
    # Start a transaction to prevent other threads from using it:
    assert oConnection.fbStartTransaction(n0zTransactionTimeoutInSeconds), \
         "Cannot start a transaction on a new connection (%s)" % repr(oConnection);
    # remove a pending connection and add it.
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__uPendingConnects -= 1;
      oSelf.__aoConnections.append(oConnection);
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    # Add some event handlers
    oConnection.fAddCallback("request sent", oSelf.__fHandleRequestSentCallbackFromConnection);
    oConnection.fAddCallback("response received", oSelf.__fHandleResponseReceivedCallbackFromConnection);
    oConnection.fAddCallback("terminated", oSelf.__fHandleTerminatedCallbackFromConnection);
    oSelf.fFireCallbacks("new connection", oConnection);
    return oConnection;
  
  def __fHandleResolveHostnameCallback(oSelf, sbHostname, iFamily, sCanonicalName, sIPAddress):
    oSelf.fFireCallbacks("hostname resolved", sbHostname = sbHostname, iFamily = iFamily, sCanonicalName = sCanonicalName, sIPAddress = sIPAddress);
  
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
      oSelf.__fReportTerminatedIfNoMoreConnectionsExist();
  
  def fasGetDetails(oSelf):
    uConnectionsCount = oSelf.uConnectionsCount;
    bTerminated = oSelf.bTerminated;
    return [s for s in [
      str(oSelf.__oServerBaseURL.sbBase, 'latin1'),
      "%d connections" % uConnectionsCount if not bTerminated else None,
      "secure" if oSelf.__o0SSLContext else None,
      "terminated" if bTerminated else
          "stopping" if oSelf.__bStopping else None,
    ] if s];
  
  def __repr__(oSelf):
    sModuleName = ".".join(oSelf.__class__.__module__.split(".")[:-1]);
    return "<%s.%s#%X|%s>" % (sModuleName, oSelf.__class__.__name__, id(oSelf), "|".join(oSelf.fasGetDetails()));
  
  def __str__(oSelf):
    return "%s#%X{%s}" % (oSelf.__class__.__name__, id(oSelf), ", ".join(oSelf.fasGetDetails()));
