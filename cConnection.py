try: # mDebugOutput use is Optional
  from mDebugOutput import ShowDebugOutput, fShowDebugOutput;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mDebugOutput'":
    raise;
  ShowDebugOutput = lambda fx: fx; # NOP
  fShowDebugOutput = lambda x, s0 = None: x; # NOP

from mHTTPProtocol import (
  cHeaders,
  cInvalidMessageException,
  cRequest,
  cResponse,
  cURL,
  iMessage,
);
from mNotProvided import (
  fxGetFirstProvidedValue,
  zNotProvided,
);
from mTCPIPConnection import (
  cTransactionalBufferedTCPIPConnection
);

from .mExceptions import (
  cConnectionOutOfBandDataException,
);

gbDebugOutputFullHTTPMessages = False;

class cConnection(cTransactionalBufferedTCPIPConnection):
  u0DefaultMaxReasonPhraseSize = 1000;
  u0DefaultMaxHeaderLineSize = 10*1000;
  u0DefaultMaxNumberOfHeaders = 256;
  u0DefaultMaxBodySize = 1000*1000*1000;
  u0DefaultMaxChunkSize = 10*1000*1000;
  u0DefaultMaxNumberOfChunks = 1000*1000;
  n0DefaultTransactionTimeoutInSeconds = 10;
  # The HTTP RFC does not provide an upper limit to the maximum number of characters a chunk size can contain.
  # So, by padding a valid chunk size on the left with "0", one could theoretically create a valid chunk header that has
  # an infinite size. To prevent us accepting such an obviously invalid value, we will accept no chunk size containing
  # more than 16 chars (i.e. 64-bit numbers).
  u0MaxChunkSizeCharacters = 16;
  def __init__(oSelf, *txArguments, **dxArguments):
    super().__init__(*txArguments, **dxArguments);
    oSelf.fAddEvents(
      "sending message",
      "sending message failed",
      "sent message",
      
      "receiving message",
      "receiving message failed",
      "received message", 
      
      "received out-of-band data from server",

      "sending request to server",
      "sending request to server failed",
      "sent request to server",
      
      "receiving request from client",
      "receiving request from client failed",
      "received request from client",
      
      "sending response to client",
      "sending response to client failed",
      "sent response to client",
      
      "receiving response from server",
      "receiving response from server failed",
      "received response from server",
    );
  
  def foGetURLForRemoteServer(oSelf):
    # Calling this only makes sense from a client on a connection to a server.
    return cURL(b"https" if oSelf.bSecure else b"http", oSelf.sbRemoteHost, oSelf.uRemotePortNumber);

  @ShowDebugOutput
  def fThrowExceptionIfSendingRequestIsNotPossible(oSelf):
    oSelf.fThrowExceptionIfShutdownOrDisconnected();
    if oSelf.fbBytesAreAvailableForReading():
      sbOutOfBandData = oSelf.fsbReadAvailableBytes();
      fShowDebugOutput(oSelf, "Connection has out-of-band data from server: %s: %s." % (oSelf, repr(sbOutOfBandData)));
      oSelf.fFireCallbacks("received out-of-band data from server", sbOutOfBandData = sbOutOfBandData);
      oSelf.fTerminate();
      raise cConnectionOutOfBandDataException(
        "received out-of-band data from server",
        o0Connection = oSelf,
        dxDetails = {"sbOutOfBandData": sbOutOfBandData},
      );

  # Send HTTP Messages
  @ShowDebugOutput
  def fSendRequest(oSelf,
    oRequest,
  ):
    oSelf.fThrowExceptionIfSendingRequestIsNotPossible();
    # Attempt to write a request to the connection.
    # * The connection must be fully open (== not shut down for reading or writing
    #   or closed). A `shutdown` or `disconnected` exception is thrown as
    #   appropriate if this is not the case.
    # * The connection must not have any buffered data from the server. An
    #   `out-of-band data` exception is thrown if there is data in the buffer.
    # Can throw out-of-band data, timeout, shutdown or disconnected exception.
    oSelf.fFireCallbacks("sending request to server", oRequest = oRequest);
    try:
      oSelf.__fSendMessage(oRequest);
    except Exception as oException:
      oSelf.__o0LastSentRequest = None;
      oSelf.fFireCallbacks("sending request to server failed", oRequest = oRequest, oException = oException);
      oSelf.fTerminate();
      raise;
    oSelf.__o0LastSentRequest = oRequest;
    oSelf.fFireCallbacks( "sent request to server", oRequest = oRequest);
    return True;
  
  @ShowDebugOutput
  def fSendResponse(oSelf,
    oResponse,
  ):
    o0Request = oSelf.__o0LastReceivedRequest;
    oSelf.fFireCallbacks("sending response to client", o0Request = o0Request, oResponse = oResponse);
    # Attempt to write a response to the connection.
    # Can throw timeout, shutdown or disconnected exception.
    try:
      oSelf.__fSendMessage(oResponse);
    except Exception as oException:
      oSelf.__o0LastReceivedRequest = None;
      oSelf.fFireCallbacks("sending response to client failed", o0Request = o0Request, oResponse = oResponse, oException = oException);
      oSelf.fTerminate();
      raise;
    oSelf.__o0LastReceivedRequest = None;
    oSelf.fFireCallbacks("sent response to client", o0Request = o0Request, oResponse = oResponse);
  
  @ShowDebugOutput
  def __fSendMessage(oSelf,
    oMessage,
  ):
    # Serialize and send the cHTTPMessage instance.
    # Can throw timeout, shutdown or disconnected exception.
    oSelf.fFireCallbacks("sending message", oMessage = oMessage);
    sbMessage = oMessage.fsbSerialize();
    try:
      oSelf.fWriteBytes(sbMessage);
    except Exception as oException:
      oSelf.fFireCallbacks("sending message failed", oException = oException, oMessage = oMessage);
      raise;
    else:
      fShowDebugOutput("%s sent to %s." % (oMessage, oSelf));
      if gbDebugOutputFullHTTPMessages:
        fShowDebugOutput(str(sbMessage, 'latin1'));
      oSelf.fFireCallbacks("sent message", oMessage = oMessage);
  
  # Read HTTP Messages
  @ShowDebugOutput
  def foReceiveRequest(oSelf,
    u0zMaxStartLineSize = zNotProvided,
    u0zMaxHeaderLineSize = zNotProvided,
    u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided,
    u0zMaxChunkSize = zNotProvided,
    u0zMaxNumberOfChunks = zNotProvided, # throw exception if more than this many chunks are received
  ):
    oSelf.fFireCallbacks("receiving request from client");
    # Attempt to receive a request from the connection.
    # If an exception is thrown, a transaction started here will be ended again.
    # Return None if an optional transaction could not be started.
    # Returns a cRequest object if a request was received.
    # Can throw timeout, shutdown or disconnected exception.
    try:
      oRequest = oSelf.__foReceiveMessage(
        # it's ok if a connection is dropped by a client before a request is received, so the above can return None.
        cRequest, 
        u0zMaxStartLineSize = u0zMaxStartLineSize,
        u0zMaxHeaderLineSize = u0zMaxHeaderLineSize,
        u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
        u0zMaxBodySize = u0zMaxBodySize,
        u0zMaxChunkSize = u0zMaxChunkSize,
        u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
        u0MaxNumberOfChunksBeforeDisconnecting = None,
        bCanHaveBody = True, # Only for response to HEAD request
      );
    except Exception as oException:
      oSelf.__o0LastReceivedRequest = None;
      oSelf.fFireCallbacks("receiving request from client failed", oException = oException);
      oSelf.fTerminate();
      raise;
    oSelf.__o0LastReceivedRequest = oRequest;
    oSelf.fFireCallbacks("received request from client", oRequest = oRequest);
    return oRequest;

  @ShowDebugOutput
  def foReceiveResponse(oSelf,
    u0zMaxStartLineSize = None,
    u0zMaxHeaderLineSize = None,
    u0zMaxNumberOfHeaders = None,
    u0zMaxBodySize = None,
    u0zMaxChunkSize = None,
    u0zMaxNumberOfChunks = None, # throw exception if more than this many chunks are received
    u0MaxNumberOfChunksBeforeDisconnecting = None, # disconnect and return response once this many chunks are received.
  ):
    # Attempt to receive a response from the connection.
    # Optionally end a transaction after doing so, even if an exception is thrown.
    # Returns a cResponse object.
    # Can throw timeout, shutdown or disconnected exception.
    assert oSelf.bInTransaction, \
        "A transaction must be started before a response can be received over this connection.";
    o0Request = oSelf.__o0LastSentRequest;
    oSelf.fFireCallbacks("receiving response from server", o0Request = o0Request);
    try:
      oResponse = oSelf.__foReceiveMessage(
        # it's not ok if a connection is dropped by a server before a response is received, so the above cannot return None.
        cResponse, 
        u0zMaxStartLineSize = u0zMaxStartLineSize,
        u0zMaxHeaderLineSize = u0zMaxHeaderLineSize,
        u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
        u0zMaxBodySize = u0zMaxBodySize,
        u0zMaxChunkSize = u0zMaxChunkSize,
        u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
        u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
        bCanHaveBody = o0Request is None or o0Request.sbMethod != b"HEAD", # Response to HEAD request cannot have body
      );
    except Exception as oException:
      oSelf.__o0LastSentRequest = None;
      oSelf.fFireCallbacks("receiving response from server failed", o0Request = o0Request, oException = oException);
      oSelf.fTerminate();
      raise;
    oSelf.__o0LastSentRequest = None;
    oSelf.fFireCallbacks("received response from server", o0Request = o0Request, oResponse = oResponse);
    return oResponse;
  
  @ShowDebugOutput
  def __foReceiveMessage(oSelf,
    cMessage: iMessage,
    u0zMaxStartLineSize: int | None | type(zNotProvided) = zNotProvided,
    u0zMaxHeaderLineSize: int | None | type(zNotProvided) = zNotProvided,
    u0zMaxNumberOfHeaders: int | None | type(zNotProvided) = zNotProvided,
    u0zMaxBodySize: int | None | type(zNotProvided) = zNotProvided,
    u0zMaxChunkSize: int | None | type(zNotProvided) = zNotProvided,
    u0zMaxNumberOfChunks: int | None | type(zNotProvided) = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting: int | None = None,
    bCanHaveBody: bool = True, # Only for response to HEAD request
  ):
    # Read and parse a HTTP message.
    # Returns a cMessage instance.
    # Can throw timeout, shutdown or disconnected exception.
    u0MaxStartLineSize  = fxGetFirstProvidedValue(u0zMaxStartLineSize,   oSelf.u0DefaultMaxReasonPhraseSize);
    u0MaxHeaderLineSize  = fxGetFirstProvidedValue(u0zMaxHeaderLineSize,   oSelf.u0DefaultMaxHeaderLineSize);
    u0MaxNumberOfHeaders = fxGetFirstProvidedValue(u0zMaxNumberOfHeaders,  oSelf.u0DefaultMaxNumberOfHeaders);
    u0MaxBodySize        = fxGetFirstProvidedValue(u0zMaxBodySize,         oSelf.u0DefaultMaxBodySize);
    u0MaxChunkSize       = fxGetFirstProvidedValue(u0zMaxChunkSize,        oSelf.u0DefaultMaxChunkSize);
    u0MaxNumberOfChunks  = fxGetFirstProvidedValue(u0zMaxNumberOfChunks, oSelf.u0DefaultMaxNumberOfChunks);
    assert (
      u0MaxNumberOfChunksBeforeDisconnecting is None or
      u0MaxNumberOfChunks > u0MaxNumberOfChunksBeforeDisconnecting
    ), \
        "u0MaxNumberOfChunksBeforeDisconnecting (%d) must be less than u0MaxNumberOfChunks (%d)." % (
          u0MaxNumberOfChunksBeforeDisconnecting,
          u0MaxNumberOfChunks,
        );
    oSelf.fFireCallbacks("receiving message");
    try:
      # Read and parse start line
      dxConstructorStartLineArguments = oSelf.__fdxReadAndDeserializeStartLine(
        cMessage,
        u0MaxStartLineSize,
      );
      # Read and parse headers
      o0Headers = oSelf.__fo0ReadAndDeserializeHeaders(
        cMessage,
        u0MaxHeaderLineSize,
        u0MaxNumberOfHeaders,
      );
      # Find out what headers are present and at the same time do some sanity checking:
      # (this can throw a cInvalidMessageException if multiple Content-Length headers exist with different values)
      oMessage = cMessage(
        o0zHeaders = o0Headers,
        **dxConstructorStartLineArguments
      );
      if bCanHaveBody:
        if oMessage.fbHasChunkedEncodingHeader():
          sbChunkedBody = oSelf.__fsbReadChunkedBody(
            u0MaxBodySize,
            u0MaxChunkSize,
            u0MaxNumberOfChunks,
            u0MaxNumberOfChunksBeforeDisconnecting,
            u0MaxHeaderLineSize, # We use the same value for the headers and the trailer.
          );
          oMessage.fSetBody(sbChunkedBody);
        else:
          u0ContentLength = o0Headers and o0Headers.fu0GetContentLength(u0MaxBodySize);
          if u0ContentLength is not None:
            fShowDebugOutput("Reading %d bytes message body..." % u0ContentLength);
            sbBody = oSelf.fsbReadBytes(u0ContentLength);
            fShowDebugOutput("Message body is %d bytes." % len(sbBody));
            oMessage.fSetBody(sbBody);
          elif cMessage.bCanHaveBodyIfConnectionCloseHeaderIsPresent and \
              o0Headers and oMessage.fbHasConnectionCloseHeader():
            fShowDebugOutput("Reading response body until closed...");
            sbBody = oSelf.fsbReadBytesUntilShutdown(u0MaxNumberOfBytes = u0MaxBodySize);
            fShowDebugOutput("Response body is %d bytes." % len(sbBody));
            oMessage.fSetBody(sbBody);
    except Exception as oException:
      oSelf.fFireCallbacks("receiving message failed", oException);
      raise;
    fShowDebugOutput("%s received from %s." % (oMessage, oSelf));
    if gbDebugOutputFullHTTPMessages:
      fShowDebugOutput(str(oMessage.fsbSerialize(), 'latin1'));
    
    oSelf.fFireCallbacks("received message", oMessage);
    
    return oMessage;
  
  @ShowDebugOutput
  def __fdxReadAndDeserializeStartLine(oSelf,
    cMessage,
    u0MaxStartLineSize,
  ):
    fShowDebugOutput("Reading start line...");
    sb0StartLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxStartLineSize);
    if sb0StartLineCRLF is None:
      sbStartLine = oSelf.fsbReadBufferedData();
      raise cInvalidMessageException(
        "The start line was too large.",
        o0Connection = oSelf,
        dxDetails = {"sbStartLine": sbStartLine, "u0MaxStartLineSize": u0MaxStartLineSize},
      );
    fShowDebugOutput("Parsing start line...");
    return cMessage.fdxDeserializeStartLine(sb0StartLineCRLF[:-2]);
  
  @ShowDebugOutput
  def __fo0ReadAndDeserializeHeaders(oSelf,
    cMessage,
    u0MaxHeaderLineSize,
    u0MaxNumberOfHeaders,
  ):
    fShowDebugOutput("Reading headers...");
    asbHeaderLines = [];
    while 1:
      sb0HeaderLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxHeaderLineSize);
      if sb0HeaderLineCRLF is None:
        sbHeaderLine = oSelf.fsbReadBufferedData();
        raise cInvalidMessageException(
          "A header line was too large.",
          o0Connection = oSelf,
          dxDetails = {"sbHeaderLine": sbHeaderLine, "u0MaxHeaderLineSize": u0MaxHeaderLineSize},
        );
      sbHeaderLine = sb0HeaderLineCRLF[:-2];
      if len(sbHeaderLine) == 0:
        break; # Empty line == end of headers
      asbHeaderLines.append(sbHeaderLine);
    if len(asbHeaderLines) == 0:
      return None;
    return cHeaders.foDeserializeLines(asbHeaderLines);
  
  @ShowDebugOutput
  def __fsbReadChunkedBody(oSelf,
    u0MaxBodySize,
    u0MaxChunkSize,
    u0MaxNumberOfChunks,
    u0MaxNumberOfChunksBeforeDisconnecting,
    u0MaxTrailerLineSize,
  ):
    fShowDebugOutput("Reading chunked response body...");
    sbChunkedBody = b"";
    uTotalNumberOfBodyChunks = 0;
    while 1:
      if u0MaxNumberOfChunksBeforeDisconnecting is not None:
        uMaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting;
        if uTotalNumberOfBodyChunks == uMaxNumberOfChunksBeforeDisconnecting:
          oSelf.fDisconnect();
          return abChunkedBody;
      if u0MaxNumberOfChunks is not None and uTotalNumberOfBodyChunks == u0MaxNumberOfChunks:
        raise cInvalidMessageException(
          "The number of body chunks was larger than the maximum expected.",
          o0Connection = oSelf,
          dxDetails = {"uMaxNumberOfChunks": u0MaxNumberOfChunks, "uMinimumNumberOfChunksInBody": u0MaxNumberOfChunks + 1},
        );
      fShowDebugOutput("Reading response body chunk #%d header line..." % (uTotalNumberOfBodyChunks + 1));
      # Read size in the chunk header
      u0MaxChunkHeaderLineSize = oSelf.u0MaxChunkSizeCharacters + 2 if oSelf.u0MaxChunkSizeCharacters is not None else None;
      bLimitedByTotalBodySize = u0MaxBodySize is not None and u0MaxBodySize - len(sbChunkedBody) < u0MaxChunkHeaderLineSize;
      if bLimitedByTotalBodySize:
        u0MaxChunkHeaderLineSize = u0MaxBodySize - len(sbChunkedBody);
      sb0ChunkHeaderLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxChunkHeaderLineSize);
      if sb0ChunkHeaderLineCRLF is None:
        sbChunkHeaderLine = oSelf.fsbReadBufferedData();
        if bLimitedByTotalBodySize:
          sbChunkedBody += sbChunkHeaderLine;
          raise cInvalidMessageException(
            "The chunked body was larger than the maximum accepted.",
            o0Connection = oSelf,
            dxDetails = {"uMaxBodySize": u0MaxBodySize, "uMinimumNumberOfBytesInBodyChunks": len(sbChunkedBody)},
          );
        else:
          raise cInvalidMessageException(
            "A body chunk header line was larger than the maximum accepted.",
            o0Connection = oSelf,
            dxDetails = {"uMaxChunkHeaderLineSize": u0MaxChunkHeaderLineSize, "uMinimumNumberOfBytesInChunkHeader": len(sbChunkHeaderLine)},
          );
      sbChunkedBody += sb0ChunkHeaderLineCRLF;
      uIndexOfExtensionSeparator = sb0ChunkHeaderLineCRLF.find(b";");
      if uIndexOfExtensionSeparator != -1:
        sbChunkSize = sb0ChunkHeaderLineCRLF[:uIndexOfExtensionSeparator];
      else:
        sbChunkSize = sb0ChunkHeaderLineCRLF[:-2];
      try:
        uChunkSize = int(sbChunkSize, 16);
      except ValueError:
        raise cInvalidMessageException(
          "A body chunk header line contained an invalid character in the chunk size.",
          o0Connection = oSelf,
          dxDetails = {"sb0ChunkHeaderLineCRLF": sb0ChunkHeaderLineCRLF},
        );
      if uChunkSize == 0:
        break; # end of chunked body
      if u0MaxChunkSize is not None and uChunkSize > u0MaxChunkSize:
        raise cInvalidMessageException(
          "A body chunk was larger than the maximum accepted",
          o0Connection = oSelf,
          dxDetails = {"uMaxChunkSize": u0MaxChunkSize, "uChunkSize": uChunkSize},
        );
      # Check chunk size and number of chunks
      uMinimumChunkedBodySize = len(sbChunkedBody) + uChunkSize + 5; # add 5 because we expect at least "\r\n0\r\n" after this chunk"
      if u0MaxBodySize is not None and u0MaxBodySize < uMinimumChunkedBodySize:
        raise cInvalidMessageException(
          "The chunked body was larger than the maximum accepted.",
          o0Connection = oSelf,
          dxDetails = {"uMaxBodySize": uMaxBodySize, "uMinimumChunkedBodySize": uMinimumChunkedBodySize},
        );
      # Read the chunk
      fShowDebugOutput("Reading response body chunk #%d (%d bytes)..." % (uTotalNumberOfBodyChunks + 1, uChunkSize));
      sbChunkCRLF = oSelf.fsbReadBytes(uChunkSize + 2);
      if sbChunkCRLF[-2:] != b"\r\n":
        raise cInvalidMessageException(
          "A body chunk did not end with CRLF.",
          o0Connection = oSelf,
          dxDetails = {"sbChunkCRLF": sbChunkCRLF},
        );
      sbChunkedBody += sbChunkCRLF;
    # Read chunk trailer line
    while 1:
      bLimitedByTotalBodySize = u0MaxBodySize is not None and u0MaxBodySize - len(sbChunkedBody) < u0MaxTrailerLineSize;
      if bLimitedByTotalBodySize:
        u0MaxTrailerLineSize = u0MaxBodySize - len(sbChunkedBody);
      sb0TrailerLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxTrailerLineSize);
      if sb0TrailerLineCRLF is None:
        sbTrailerLine = oSelf.fsbReadBufferedData();
        if bLimitedByTotalBodySize:
          sbChunkedBody += sbTrailerLine;
          raise cInvalidMessageException(
            "The chunked body was larger than the maximum accepted.",
            o0Connection = oSelf,
            dxDetails = {"uMaxBodySize": u0MaxBodySize, "uMinimumNumberOfBytesInBodyChunks": len(sbChunkedBody)},
          );
        else:
          raise cInvalidMessageException(
            "A chunked body trailer line was larger than the maximum accepted.",
            o0Connection = oSelf,
            dxDetails = {"uMaxTrailerLineSize": u0MaxTrailerLineSize, "uMinimumNumberOfBytesInTrailer": len(sbTrailerLine)},
          );
      # Add chunk trailer line to body
      sbChunkedBody += sb0TrailerLineCRLF;
      sbTrailerLine = sb0TrailerLineCRLF[:-2];
      # If it is end, this is the end of the body
      if sbTrailerLine == b"":
        # empty line means end of trailers.
        break;
    return sbChunkedBody;
  
  @ShowDebugOutput
  def foSendRequestAndReceiveResponse(oSelf,
    # Send request arguments:
    oRequest,
    # Receive response arguments:
    u0zMaxStartLineSize = zNotProvided,
    u0zMaxHeaderLineSize = zNotProvided,
    u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided,
    u0zMaxChunkSize = zNotProvided,
    u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = None,
  ):
    oSelf.fSendRequest(oRequest);
    return oSelf.foReceiveResponse(
      u0zMaxStartLineSize = u0zMaxStartLineSize,
      u0zMaxHeaderLineSize = u0zMaxHeaderLineSize,
      u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
      u0zMaxBodySize = u0zMaxBodySize,
      u0zMaxChunkSize = u0zMaxChunkSize,
      u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
      u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
    );
