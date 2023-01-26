import time;

try: # mDebugOutput use is Optional
  from mDebugOutput import ShowDebugOutput, fShowDebugOutput;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mDebugOutput'":
    raise;
  ShowDebugOutput = lambda x: x; # NOP
  fShowDebugOutput = lambda x, y = None: x; # NOP

from mMultiThreading import cLock, cWithCallbacks;
from mNotProvided import \
    fxGetFirstProvidedValue, \
    zNotProvided;

from .cHTTPConnection import cHTTPConnection;
from .mExceptions import \
    acExceptions, \
    cHTTPMaxConnectionsToServerReachedException, \
    cTCPIPConnectionCannotBeUsedConcurrentlyException, \
    cTCPIPConnectionDisconnectedException, \
    cTCPIPConnectionShutdownException;

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
    oSelf.__aoExternallyManagedConnections = []; # The connections this pool has provided for use by others.
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
      "server hostname or ip address invalid",
      
      "resolving server hostname", "resolving server hostname failed", "server hostname resolved to ip address",
      
      "connecting to server ip address", "connecting to server ip address failed",
      "connecting to server failed", "connection to server created",
      
      "bytes written", "bytes read",
      "request sent", "response received",
      "request sent and response received",
      
      "connection to server terminated",
      
      "terminated"
    );
  
  @property
  def bTerminated(oSelf):
    return not oSelf.__oTerminatedLock.bLocked;
  
  @property
  def uConnectionsCount(oSelf):
    return len(oSelf.__aoConnections) + len(oSelf.__aoExternallyManagedConnections);
  
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
      if oSelf.__aoConnections or oSelf.__aoExternallyManagedConnections:
        if oSelf.__aoConnections:
          fShowDebugOutput("There are %d connections left." % len(oSelf.__aoConnections));
        if oSelf.__aoExternallyManagedConnections:
          fShowDebugOutput("There are %d externalized connections left." % len(oSelf.__aoExternallyManagedConnections));
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
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      aoConnectionsThatAreNotStopping = [
        oConnection
        for oConnection in oSelf.__aoConnections
        if not oConnection.bStopping
      ];
      aoExternallyManagedConnectionsThatAreNotStopping = [
        oConnection
        for oConnection in oSelf.__aoExternallyManagedConnections
        if not oConnection.bStopping
      ];
      assert not aoExternallyManagedConnectionsThatAreNotStopping, \
          "There are externally managed connections that have not been stopped yet: %s" % \
          ", ".join(str(oConnection) for oConnection in aoExternallyManagedConnectionsThatAreNotStopping);
      fShowDebugOutput("Stopping...");
      oSelf.__bStopping = True;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    # We are stopping. New connections will no longer be created.
    # Existing connections should all be stopping:
    for oConnection in aoConnectionsThatAreNotStopping:
        oConnection.fStop();
    # Check if we have already terminated, or if some connections are still stopping.
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
    bDoNotUseSLL = False,
    n0zSecureTimeoutInSeconds = zNotProvided,
    n0zTransactionTimeoutInSeconds = zNotProvided,
  ):
    # Wrapper for the internal version. This external version also marks the
    # connection as having been passed externally, to prevent it from being
    # used as part of the regular pool. The caller is responsible for closing
    # the connection.
    o0Connection = oSelf.__fo0GetConnectionAndStartTransaction(
      n0zConnectTimeoutInSeconds,
      bDoNotUseSLL,
      n0zSecureTimeoutInSeconds,
      n0zTransactionTimeoutInSeconds,
    );
    if o0Connection is None:
      assert oSelf.__bStopping, \
          "A new connection was not established even though we are not stopping!?";
      return None;
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__aoConnections.remove(o0Connection);
      oSelf.__aoExternallyManagedConnections.append(o0Connection);
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    return o0Connection;
  
  def __fo0GetConnectionAndStartTransaction(
    oSelf,
    n0zConnectTimeoutInSeconds,
    bDoNotUseSLL,
    n0zSecureTimeoutInSeconds,
    n0zTransactionTimeoutInSeconds,
  ):
    if oSelf.__bStopping:
      return None;
    fShowDebugOutput("Getting connection...");
    n0EndTime = (time.time() + n0zConnectTimeoutInSeconds) if n0zConnectTimeoutInSeconds is not None else None;
    while not oSelf.__bStopping:
      # Existing idle connections may be used:
      o0Connection = oSelf.__fo0StartTransactionOnExistingConnection(n0zTransactionTimeoutInSeconds);
      if o0Connection is not None:
        return o0Connection;
      if oSelf.__bStopping:
        return None;
      # New connections may be established; connect timeout will be reduced if we've been through this loop before
      n0zConnectTimeoutInSeconds = (n0EndTime - time.time()) if n0EndTime is not None else None;
      try:
        return oSelf.__foCreateNewConnectionAndStartTransaction(
          n0zConnectTimeoutInSeconds,
          bDoNotUseSLL,
          n0zSecureTimeoutInSeconds,
          n0zTransactionTimeoutInSeconds,
        );
      except cHTTPMaxConnectionsToServerReachedException:
        # We have reached the max number of connections; try reusing one again.
        pass;
    return None;
  
  @ShowDebugOutput
  def fo0SendRequestAndReceiveResponse(oSelf,
    oRequest,
    n0zConnectTimeoutInSeconds = zNotProvided, n0zSecureTimeoutInSeconds = zNotProvided, n0zTransactionTimeoutInSeconds = zNotProvided,
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided, u0zMaxHeaderValueSize = zNotProvided, u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided, u0zMaxChunkSize = zNotProvided, u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = zNotProvided, # disconnect and return response once this many chunks are received.
  ):
    # Send a request to the server and receive a response. A transaction on the
    # connection is started before and ended after this exchange.
    # An existing connection is reused if one is available. A new connection
    # if created if none is available and there are not too many connections.
    # If not specified, always check the hostname when the connection is secure.
    # Can throw a max-connections-reached exception.
    # This is done in a loop: if a (reused) connection turns out to be closed, 
    # we start again, reusing another connection, or creating a new one.
    while 1:
      if oSelf.__bStopping:
        return None;
      o0Connection = oSelf.__fo0GetConnectionAndStartTransaction(
        n0zConnectTimeoutInSeconds = n0zConnectTimeoutInSeconds,
        bDoNotUseSLL = False,
        n0zSecureTimeoutInSeconds = n0zSecureTimeoutInSeconds,
        n0zTransactionTimeoutInSeconds = n0zTransactionTimeoutInSeconds,
      );
      if o0Connection is None:
        assert oSelf.__bStopping, \
            "A new connection was not established even though we are not stopping!?";
        return None;
      oConnection = o0Connection;
      try:
        # Returns cResponse instance if response was received.
        return oConnection.foSendRequestAndReceiveResponse(
          oRequest,
          u0zMaxStatusLineSize = u0zMaxStatusLineSize,
          u0zMaxHeaderNameSize = u0zMaxHeaderNameSize,
          u0zMaxHeaderValueSize = u0zMaxHeaderValueSize,
          u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
          u0zMaxBodySize = u0zMaxBodySize,
          u0zMaxChunkSize = u0zMaxChunkSize,
          u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
          u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting, # disconnect and return response once this many chunks are received.
        );
      finally:
        oConnection.fEndTransaction();
  @ShowDebugOutput
  def __fo0StartTransactionOnExistingConnection(oSelf, n0zTransactionTimeoutInSeconds):
    # We need to postpone and terminate callbacks because we have a lock that
    # these callbacks also want. If we do not postpone them, there will be a
    # deadlock.
    oSelf.__oConnectionsPropertyLock.fAcquire();
    aoConnectionsWithPotentiallyPostponedTerminatedCallbacks = [];
    try:
      # Try to find a connection that is available:
      for oConnection in oSelf.__aoConnections:
        if oSelf.__bStopping:
          return None;
        fShowDebugOutput(oSelf, "Testing connection: %s" % repr(oConnection));
        oConnection.fPostponeTerminatedCallback();
        aoConnectionsWithPotentiallyPostponedTerminatedCallbacks.append(oConnection);
        try: # Try to start a transaction; this will only succeed on an idle connection.
          oConnection.fStartTransaction(n0zTransactionTimeoutInSeconds);
        except cTCPIPConnectionCannotBeUsedConcurrentlyException:
          fShowDebugOutput(oSelf, "Connection is in use.");
        except cTCPIPConnectionShutdownException:
          fShowDebugOutput(oSelf, "Connection is shut down.");
        except cTCPIPConnectionDisconnectedException:
          fShowDebugOutput(oSelf, "Connection is disconnected.");
        else:
          fShowDebugOutput(oSelf, "Transaction started: connection is available.");
          return oConnection;
      return None;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
      # Fire any postponed terminated callbacks.
      for oConnection in aoConnectionsWithPotentiallyPostponedTerminatedCallbacks:
        oConnection.fFireTerminatedCallbackIfPostponed();
  
  @ShowDebugOutput
  def __foCreateNewConnectionAndStartTransaction(oSelf,
    n0zConnectTimeoutInSeconds,
    bDoNotUseSLL,
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
       raise cHTTPMaxConnectionsToServerReachedException(
          "Maximum number of connections to server reached.",
          dxDetails = {
            "bServerIsAProxy": False,
            "uMaxNumberOfConnections": oSelf.__u0MaxNumberOfConnectionsToServer, # Cannot be None at this point
          },
        );
      oSelf.__uPendingConnects += 1;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    # Try to establish a connection:
    o0Connection = None;
    try:
      oConnection = cHTTPConnection.foConnectTo(
        sbHostnameOrIPAddress = oSelf.__oServerBaseURL.sbHostname,
        uPortNumber = oSelf.__oServerBaseURL.uPortNumber,
        n0zConnectTimeoutInSeconds = n0zConnectTimeoutInSeconds,
        o0SSLContext = None if bDoNotUseSLL else oSelf.__o0SSLContext,
        n0zSecureTimeoutInSeconds = n0zSecureTimeoutInSeconds,
        f0HostnameOrIPAddressInvalidCallback = lambda sbHostnameOrIPAddress: oSelf.fFireCallbacks(
          "server hostname or ip address invalid",
          sbHostnameOrIPAddress = sbHostnameOrIPAddress,
        ),
        f0ResolvingHostnameCallback = lambda sbHostname: oSelf.fFireCallbacks(
          "resolving server hostname",
          sbHostname = sbHostname,
        ),
        f0ResolvingHostnameFailedCallback = lambda sbHostname: oSelf.fFireCallbacks(
          "resolving server hostname failed",
          sbHostname = sbHostname,
        ),
        f0HostnameResolvedToIPAddressCallback = lambda sbHostname, sIPAddress, sCanonicalName: oSelf.fFireCallbacks(
          "server hostname resolved to ip address",
          sbHostname = sbHostname,
          sIPAddress = sIPAddress,
          sCanonicalName = sCanonicalName,
        ),
        f0ConnectingToIPAddressCallback = lambda sbHostnameOrIPAddress, uPortNumber, sIPAddress, sbzHostname: oSelf.fFireCallbacks(
          "connecting to server ip address",
          sbHostnameOrIPAddress = sbHostnameOrIPAddress,
          uPortNumber = uPortNumber,
          sIPAddress = sIPAddress,
          sbzHostname = sbzHostname,
        ),
        f0ConnectingToIPAddressFailedCallback = lambda oException, sbHostnameOrIPAddress, uPortNumber, sIPAddress, sbzHostname: oSelf.fFireCallbacks(
          "connecting to server ip address failed",
          oException = oException,
          sbHostnameOrIPAddress = sbHostnameOrIPAddress,
          uPortNumber = uPortNumber,
          sIPAddress = sIPAddress,
          sbzHostname = sbzHostname,
        ),
      );
    except cHTTPConnection.tcExceptions as oException:
      oSelf.__oConnectionsPropertyLock.fAcquire();
      try:
        oSelf.__uPendingConnects -= 1;
      finally:
        oSelf.__oConnectionsPropertyLock.fRelease();
      oSelf.fFireCallbacks(
        "connecting to server failed",
        oException = oException,
        sbHostnameOrIPAddress = oSelf.__oServerBaseURL.sbHostname,
        uPortNumber = oSelf.__oServerBaseURL.uPortNumber,
      );
      raise;
    # Start a transaction to prevent other threads from using it:
    oConnection.fStartTransaction(n0zTransactionTimeoutInSeconds);
    # Add some event handlers
    # remove a pending connection and add the connection we created.
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__uPendingConnects -= 1;
      oSelf.__aoConnections.append(oConnection);
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    oConnection.fAddCallbacks({
      "bytes written": lambda oConnection, sbBytesWritten: oSelf.fFireCallbacks(
        "bytes written", oConnection, sbBytesWritten,
      ),
      "bytes read": lambda oConnection, sbBytesRead: oSelf.fFireCallbacks(
        "bytes read", oConnection, sbBytesRead,
      ),
      "request sent": lambda oConnection, oRequest: oSelf.fFireCallbacks(
        "request sent", oConnection, oRequest
      ),
      "response received": lambda oConnection, oResponse: oSelf.fFireCallbacks(
        "response received", oConnection, oResponse
      ),
      "request sent and response received": lambda oConnection, oRequest, oResponse: oSelf.fFireCallbacks(
        "request sent and response received", oConnection, oRequest, oResponse
      ),
      "terminated": oSelf.__fHandleTerminatedCallbackFromConnection,
    });
    oSelf.fFireCallbacks(
      "connection to server created",
      oConnection = oConnection,
      sbHostnameOrIPAddress = oSelf.__oServerBaseURL.sbHostname,
    );
    return oConnection;
  
  @ShowDebugOutput
  def __fHandleTerminatedCallbackFromConnection(oSelf, oConnection):
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      if oConnection in oSelf.__aoConnections:
        oSelf.__aoConnections.remove(oConnection);
      else:
        oSelf.__aoExternallyManagedConnections.remove(oConnection);
      bCheckIfTerminated = oSelf.__bStopping and len(oSelf.__aoConnections) == 0 and len(oSelf.__aoExternallyManagedConnections) == 0;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    oSelf.fFireCallbacks(
      "connection to server terminated",
      oConnection = oConnection,
      sbHostnameOrIPAddress = oSelf.__oServerBaseURL.sbHostname,
    );
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

for cException in acExceptions:
  setattr(cHTTPConnectionsToServerPool, cException.__name__, cException);
