import time;

try: # mDebugOutput use is Optional
  from mDebugOutput import ShowDebugOutput, fShowDebugOutput;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mDebugOutput'":
    raise;
  ShowDebugOutput = lambda x: x; # NOP
  fShowDebugOutput = lambda x, y = None: x; # NOP

from mMultiThreading import (
  cLock,
  cWithCallbacks,
);
from mNotProvided import (
  fxGetFirstProvidedValue,
  fxzGetFirstProvidedValueIfAny,
  zNotProvided,
);
from mTCPIPConnection import (
  cTCPIPConnectionCannotBeUsedConcurrentlyException,
  cTCPIPConnectionShutdownException,
  cTCPIPConnectionDisconnectedException,
);

from .cHTTPConnection import cHTTPConnection;
from .mExceptions import  (
  cHTTPConnectionOutOfBandDataException,
  cHTTPMaximumNumberOfConnectionsToServerReachedException,
);

# To turn access to data store in multiple variables into a single transaction, we will create locks.
# These locks should only ever be locked for a short time; if it is locked for too long, it is considered a "deadlock"
# bug, where "too long" is defined by the following value:
gnDeadlockTimeoutInSeconds = 1; # We're not doing anything time consuming, so this should suffice.
gu0DefaultMaxNumberOfConnectionsToServer = 10;
gn0DefaultConnectionTransactionTimeoutInSeconds = 10;

class cHTTPConnectionsToServerPool(cWithCallbacks):
  @ShowDebugOutput
  def __init__(oSelf,
    oServerBaseURL,
    *,
    u0zMaxNumberOfConnectionsToServer = zNotProvided,
    o0SSLContext = None,
    nSendDelayPerByteInSeconds = 0,
    bzCheckHost = zNotProvided,
  ):
    oSelf.__oServerBaseURL = oServerBaseURL;
    oSelf.__u0MaxNumberOfConnectionsToServer = fxGetFirstProvidedValue(u0zMaxNumberOfConnectionsToServer, gu0DefaultMaxNumberOfConnectionsToServer);
    oSelf.__o0SSLContext = o0SSLContext;
    oSelf.__bzCheckHost = bzCheckHost;
    
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
    oSelf.nSendDelayPerByteInSeconds = nSendDelayPerByteInSeconds;
    
    oSelf.fAddEvents(
      "server host invalid",
      
      "resolving server hostname to ip address",
      "resolving server hostname to ip address failed",
      "resolved server hostname to ip address",
      
      "connecting to server",
      "connecting to server failed",
      "created connection to server",
      "terminated connection to server",
      
      "securing connection to server",
      "securing connection to server failed",
      "secured connection to server",
      
      "read bytes",
      "wrote bytes",
      
      "sending request to server",
      "sending request to server failed",
      "sent request to server",
      
      "receiving response from server",
      "receiving response from server failed",
      "received response from server",
      
      "received out-of-band data from server",
      
      "terminated"
    );
  
  @property
  def bTerminated(oSelf):
    return not oSelf.__oTerminatedLock.bLocked;
  
  # Check to make sure the connections to server pool is terminated before being discarded.
  def __del__(oSelf):
    assert oSelf.bTerminated, \
        "%s was not terminated before being deleted!" % oSelf;
  
  @property
  def uConnectionsCount(oSelf):
    return len(oSelf.__aoConnections) + len(oSelf.__aoExternallyManagedConnections);
  
  def fSetSendDelayPerByteInSeconds(oSelf, nSendDelayPerByteInSeconds):
    oSelf.nSendDelayPerByteInSeconds = nSendDelayPerByteInSeconds;
    for oConnection in oSelf.__aoConnections:
      oConnection.nSendDelayPerByteInSeconds = nSendDelayPerByteInSeconds;
    for oConnection in oSelf.__aoExternallyManagedConnections:
      oConnection.nSendDelayPerByteInSeconds = nSendDelayPerByteInSeconds;

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
    *,
    n0zConnectTimeoutInSeconds = zNotProvided,
    bSecureConnection = True,
    bzCheckHost = zNotProvided,
    n0zSecureTimeoutInSeconds = zNotProvided,
    n0zTransactionTimeoutInSeconds = zNotProvided,
  ):
    # Wrapper for the internal version. This external version also marks the
    # connection as having been passed externally, to prevent it from being
    # used as part of the regular pool. The caller is responsible for closing
    # the connection.
    o0Connection = oSelf.__fo0GetConnectionAndStartTransaction(
      n0zConnectTimeoutInSeconds,
      bSecureConnection,
      bzCheckHost,
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
    bSecureConnection,
    bzCheckHost,
    n0zSecureTimeoutInSeconds,
    n0zTransactionTimeoutInSeconds,
  ):
    if oSelf.__bStopping:
      return None;
    n0ConnectTimeoutInSeconds = fxGetFirstProvidedValue(n0zConnectTimeoutInSeconds, cHTTPConnection.n0DefaultConnectTimeoutInSeconds);
    fShowDebugOutput("Getting connection...");
    n0EndTime = (time.time() + n0ConnectTimeoutInSeconds) if n0ConnectTimeoutInSeconds is not None else None;
    while not oSelf.__bStopping:
      # Existing idle connections may be used:
      o0Connection = oSelf.__fo0StartTransactionOnExistingConnection(
        n0zTransactionTimeoutInSeconds,
      );
      if o0Connection is not None:
        return o0Connection;
      if oSelf.__bStopping:
        return None;
      # New connections may be established; connect timeout will be reduced if we've been through this loop before
      n0ConnectTimeoutInSeconds = (n0EndTime - time.time()) if n0EndTime is not None else None;
      try:
        return oSelf.__foCreateNewConnectionAndStartTransaction(
          n0ConnectTimeoutInSeconds,
          bSecureConnection,
          bzCheckHost,
          n0zSecureTimeoutInSeconds,
          n0zTransactionTimeoutInSeconds,
        );
      except cHTTPMaximumNumberOfConnectionsToServerReachedException:
        # We have reached the max number of connections; try reusing one again.
        pass;
    return None;
  
  @ShowDebugOutput
  def __fo0StartTransactionOnExistingConnection(oSelf,
    n0zTransactionTimeoutInSeconds,
  ):
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
        fShowDebugOutput(oSelf, "Testing if existing connection is available: %s" % repr(oConnection));
        oConnection.fPostponeTerminatedCallback();
        aoConnectionsWithPotentiallyPostponedTerminatedCallbacks.append(oConnection);
        try: # Try to start a transaction; this will only succeed on an idle connection.
          oConnection.fStartTransaction(
            n0TimeoutInSeconds = fxGetFirstProvidedValue(n0zTransactionTimeoutInSeconds, gn0DefaultConnectionTransactionTimeoutInSeconds),
          );
          oConnection.fThrowExceptionIfSendingRequestIsNotPossible();
        except cTCPIPConnectionCannotBeUsedConcurrentlyException:
          fShowDebugOutput(oSelf, "Connection is use: %s." % oConnection);
        except cTCPIPConnectionShutdownException:
          fShowDebugOutput(oSelf, "Connection shut down: %s." % oConnection);
          oConnection.fDisconnect();
        except cTCPIPConnectionDisconnectedException:
          fShowDebugOutput(oSelf, "Connection disconnected: %s." % oConnection);
        except cHTTPConnectionOutOfBandDataException:
          fShowDebugOutput(oSelf, "Connection received out-of-band data: %s." % oConnection);
          oConnection.fDisconnect();
        else:
          fShowDebugOutput(oSelf, "Reusing existing connection to server: %s." % oConnection);
          return oConnection;
      return None;
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
      # Fire any postponed terminated callbacks.
      for oConnection in aoConnectionsWithPotentiallyPostponedTerminatedCallbacks:
        oConnection.fFireTerminatedCallbackIfPostponed();
  
  @ShowDebugOutput
  def __foCreateNewConnectionAndStartTransaction(oSelf,
    n0ConnectTimeoutInSeconds,
    bSecureConnection,
    bzCheckHost,
    n0zSecureTimeoutInSeconds,
    n0zTransactionTimeoutInSeconds,
  ):
    # Make sure we would not create too many connections and add a pending connection:
    # Can throw a max-connections-reached exception
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      if (
        oSelf.__u0MaxNumberOfConnectionsToServer is not None
        and len(oSelf.__aoConnections) + oSelf.__uPendingConnects == oSelf.__u0MaxNumberOfConnectionsToServer
      ):
        raise cHTTPMaximumNumberOfConnectionsToServerReachedException(
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
    try:
      oConnection = cHTTPConnection.foConnectTo(
        sbHost = oSelf.__oServerBaseURL.sbHost,
        uPortNumber = oSelf.__oServerBaseURL.uPortNumber,
        n0zConnectTimeoutInSeconds = n0ConnectTimeoutInSeconds,
        o0SSLContext = oSelf.__o0SSLContext if bSecureConnection else None,
        bzCheckHost = fxzGetFirstProvidedValueIfAny(bzCheckHost, oSelf.__bzCheckHost),
        n0zSecureTimeoutInSeconds = n0zSecureTimeoutInSeconds,
        nSendDelayPerByteInSeconds = oSelf.nSendDelayPerByteInSeconds,
        f0HostInvalidCallback = lambda sbHost: oSelf.fFireCallbacks(
          "server host invalid",
          sbHost = sbHost,
        ),
        f0ResolvingHostnameCallback = lambda sbHostname: oSelf.fFireCallbacks(
          "resolving server hostname to ip address",
          sbHostname = sbHostname,
        ),
        f0ResolvingHostnameFailedCallback = lambda sbHostname: oSelf.fFireCallbacks(
          "resolving server hostname to ip address failed",
          sbHostname = sbHostname,
        ),
        f0HostnameResolvedToIPAddressCallback = lambda sbHostname, sbIPAddress, sCanonicalName: oSelf.fFireCallbacks(
          "resolved server hostname to ip address",
          sbHostname = sbHostname,
          sbIPAddress = sbIPAddress,
          sCanonicalName = sCanonicalName,
        ),
        f0ConnectingToIPAddressCallback = lambda sbHost, uPortNumber, sbIPAddress: oSelf.fFireCallbacks(
          "connecting to server",
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
        ),
        f0ConnectingToIPAddressFailedCallback = lambda oException, sbHost, uPortNumber, sbIPAddress: oSelf.fFireCallbacks(
          "connecting to server failed",
          oException = oException,
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
        ),
        f0ConnectedToIPAddressCallback = lambda sbHost, uPortNumber, sbIPAddress, oConnection: oSelf.fFireCallbacks(
          "created connection to server",
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
          oConnection = oConnection,
        ),
        f0SecuringConnectionCallback = lambda sbHost, uPortNumber, sbIPAddress, oConnection, oSSLContext: oSelf.fFireCallbacks(
          "securing connection to server",
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
          oConnection = oConnection,
          oSSLContext = oSSLContext,
        ),
        f0SecuringConnectionFailedCallback = lambda oException, sbHost, uPortNumber, sbIPAddress, oConnection, oSSLContext: oSelf.fFireCallbacks(
          "securing connection to server failed",
          oException = oException,
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
          oConnection = oConnection,
          oSSLContext = oSSLContext,
        ),
        f0ConnectionSecuredCallback = lambda sbHost, uPortNumber, sbIPAddress, oConnection, oSSLContext: oSelf.fFireCallbacks(
          "secured connection to server",
          sbHost = sbHost,
          uPortNumber = uPortNumber,
          sbIPAddress = sbIPAddress,
          oConnection = oConnection,
          oSSLContext = oSSLContext,
        ),
      );
    except:
      oSelf.__oConnectionsPropertyLock.fAcquire();
      try:
        oSelf.__uPendingConnects -= 1;
      finally:
        oSelf.__oConnectionsPropertyLock.fRelease();
      raise;
    # Start a transaction to prevent other threads from using it:
    oConnection.fStartTransaction(
      n0TimeoutInSeconds = fxGetFirstProvidedValue(n0zTransactionTimeoutInSeconds, gn0DefaultConnectionTransactionTimeoutInSeconds),
    );
    # Add some event handlers
    # remove a pending connection and add the connection we created.
    oSelf.__oConnectionsPropertyLock.fAcquire();
    try:
      oSelf.__uPendingConnects -= 1;
      oSelf.__aoConnections.append(oConnection);
    finally:
      oSelf.__oConnectionsPropertyLock.fRelease();
    oConnection.fAddCallbacks({
      "wrote bytes": lambda oConnection, *, sbBytes: oSelf.fFireCallbacks(
        "wrote bytes", oConnection = oConnection, sbBytes = sbBytes,
      ),
      "read bytes": lambda oConnection, *, sbBytes: oSelf.fFireCallbacks(
        "read bytes", oConnection = oConnection, sbBytes = sbBytes,
      ),
      "received out-of-band data from server": lambda oConnection, *, sbOutOfBandData: oSelf.fFireCallbacks(
        "received out-of-band data from server", oConnection = oConnection, sbOutOfBandData = sbOutOfBandData,
      ),
      "sending request to server": lambda oConnection, *, oRequest: oSelf.fFireCallbacks(
        "sending request to server", oConnection = oConnection, oRequest = oRequest,
      ),
      "sending request to server failed": lambda oConnection, *, oRequest, oException: oSelf.fFireCallbacks(
        "sending request to server failed", oConnection = oConnection, oRequest = oRequest, oException = oException,
      ),
      "sent request to server": lambda oConnection, *, oRequest: oSelf.fFireCallbacks(
        "sent request to server", oConnection = oConnection, oRequest = oRequest,
      ),
      "receiving response from server": lambda oConnection, *, o0Request: oSelf.fFireCallbacks(
        "receiving response from server", oConnection = oConnection, o0Request = o0Request,
      ),
      "receiving response from server failed": lambda oConnection, *, o0Request, oException: oSelf.fFireCallbacks(
        "receiving response from server failed", oConnection = oConnection, o0Request = o0Request, oException = oException,
      ),
      "received response from server": lambda oConnection, *, o0Request, oResponse: oSelf.fFireCallbacks(
        "received response from server", oConnection = oConnection, o0Request = o0Request, oResponse = oResponse,
      ),
      "terminated": oSelf.__fHandleTerminatedCallbackFromConnection,
    });
    return oConnection;
  
  @ShowDebugOutput
  def fo0SendRequestAndReceiveResponse(oSelf,
    oRequest,
    n0zConnectTimeoutInSeconds = zNotProvided,
    n0zSecureTimeoutInSeconds = zNotProvided,
    n0zTransactionTimeoutInSeconds = zNotProvided,
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided,
    u0zMaxHeaderValueSize = zNotProvided,
    u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided,
    u0zMaxChunkSize = zNotProvided,
    u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = zNotProvided, # disconnect and return response once this many chunks are received.
  ):
    # Send a request to the server and receive a response. A transaction on the
    # connection is started before and ended after this exchange.
    # An existing connection is reused if one is available. A new connection
    # if created if none is available and there are not too many connections.
    # If not specified, always check the host when the connection is secure.
    # Can throw a max-connections-reached exception.
    # This is done in a loop: if a (reused) connection turns out to be closed, 
    # we start again, reusing another connection, or creating a new one.
    while 1:
      if oSelf.__bStopping:
        return None;
      o0Connection = oSelf.__fo0GetConnectionAndStartTransaction(
        n0zConnectTimeoutInSeconds = n0zConnectTimeoutInSeconds,
        bSecureConnection = True,
        bzCheckHost = oSelf.__bzCheckHost,
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
        oResponse = oConnection.foSendRequestAndReceiveResponse(
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
        if oRequest.fbContainsConnectionCloseHeader():
          fShowDebugOutput("Closing connection per client request...");
          oConnection.fDisconnect();
        elif oResponse.fbContainsConnectionCloseHeader():
          fShowDebugOutput("Closing connection per server response...");
          oConnection.fDisconnect();
      finally:
        oConnection.fEndTransaction();
      return oResponse;
  
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
      "terminated connection to server",
      sbHost = oSelf.__oServerBaseURL.sbHost,
      sbIPAddress = oConnection.sbRemoteIPAddress,
      uPortNumber = oSelf.__oServerBaseURL.uPortNumber,
      oConnection = oConnection,
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
