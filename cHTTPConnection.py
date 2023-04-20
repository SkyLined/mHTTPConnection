try: # mDebugOutput use is Optional
  from mDebugOutput import ShowDebugOutput, fShowDebugOutput;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mDebugOutput'":
    raise;
  ShowDebugOutput = lambda fx: fx; # NOP
  fShowDebugOutput = lambda x, s0 = None: x; # NOP

from mHTTPProtocol import cHTTPRequest, cHTTPResponse, cURL;
from mNotProvided import \
  fxGetFirstProvidedValue, \
  zNotProvided;
from mTCPIPConnection import cTransactionalBufferedTCPIPConnection;

from .mExceptions import \
    acExceptions, \
    cHTTPInvalidMessageException, \
    cHTTPOutOfBandDataException, \
    cTCPIPConnectionDisconnectedException, \
    cTCPIPConnectionShutdownException;

gbDebugOutputFullHTTPMessages = False;

class cHTTPConnection(cTransactionalBufferedTCPIPConnection):
  u0DefaultMaxReasonPhraseSize = 1000;
  u0DefaultMaxHeaderNameSize = 10*1000;
  u0DefaultMaxHeaderValueSize = 10*1000;
  u0DefaultMaxNumberOfHeaders = 256;
  u0DefaultMaxBodySize = 1000*1000*1000;
  u0DefaultMaxChunkSize = 10*1000*1000;
  u0DefaultMaxNumberOfChunks = 1000*1000;
  bAllowOutOfBandData = True;
  # The HTTP RFC does not provide an upper limit to the maximum number of characters a chunk size can contain.
  # So, by padding a valid chunk size on the left with "0", one could theoretically create a valid chunk header that has
  # an infinite size. To prevent us accepting such an obviously invalid value, we will accept no chunk size containing
  # more than 16 chars (i.e. 64-bit numbers).
  u0MaxChunkSizeCharacters = 16;
  cHTTPRequest = cHTTPRequest;
  cHTTPResponse = cHTTPResponse;
  
  # Create HTTP Messages
  @staticmethod
  def foCreateRequest(*txArguments, **dxArguments):
    return cHTTPRequest(*txArguments, **dxArguments);
  
  @staticmethod
  def foCreateResponse(*txArguments, **dxArguments):
    return cHTTPResponse(*txArguments, **dxArguments);
  
  def __init__(oSelf, *txArguments, **dxArguments):
    super(cHTTPConnection, oSelf).__init__(*txArguments, **dxArguments);
    oSelf.fAddEvents(
      "message sent", "message received", 
      "request sent", "response received", "request sent and response received",
      "request received", "response sent", "request received and response sent",
    );
  
  def foGetURLForRemoteServer(oSelf):
    # Calling this only makes sense from a client on a connection to a server.
    return cURL(b"https" if oSelf.bSecure else b"http", oSelf.sbRemoteHostname, oSelf.uRemotePortNumber);
  
  # Send HTTP Messages
  @ShowDebugOutput
  def fSendRequest(oSelf,
    oRequest,
  ):
    # Attempt to write a request to the connection.
    # * Optionally end a transaction after attempting to send the request.
    #   The transaction is always ended, even on an exception, except if
    #   a transaction already exists for the connection and this function
    #   is asked to start a new one.
    # * The connection must be fully open (== not shut down for reading or writing
    #   or closed). A `shutdown` or `disconnected` exception is thrown as
    #   appropriate if this is not the case.
    # * an `out-of-band-data` exception is thrown if there is data from the server
    #   available on the connection.
    # return False if an optional transaction could not be started.
    # return True if the request was sent.
    # Can throw timeout, out-of-band-data, shutdown or disconnected exception.
    # The server should only send data in response to a request; if it sent out-of-band data we close the connection.
    if not oSelf.bAllowOutOfBandData:
      sbOutOfBandData = oSelf.fsbReadAvailableBytes();
      if sbOutOfBandData:
        # The request will not be send because the server sent out-of-band data.
        oSelf.fDisconnect();
        # This is an unexpected error by the server: raise an exception to
        # report it.
        raise cHTTPOutOfBandDataException(
          "Out-of-band data was received before request was sent!",
          o0Connection = oSelf,
          dxDetails = {
            "sbOutOfBandData": sbOutOfBandData
          },
        );
    oSelf.__fSendMessage(oRequest);
    oSelf.fFireCallbacks("request sent", oRequest = oRequest);
    oSelf.__o0LastSentRequest = oRequest;
    return True;
  
  @ShowDebugOutput
  def fSendResponse(oSelf, oResponse):
    # Attempt to write a response to the connection.
    # Can throw timeout, shutdown or disconnected exception.
    oSelf.__fSendMessage(oResponse);
    oLastReceivedRequest = oSelf.__o0LastReceivedRequest;
    oSelf.__o0LastReceivedRequest = None;
    oSelf.fFireCallbacks("response sent", oResponse = oResponse);
    if oSelf.__o0LastReceivedRequest:
      oSelf.fFireCallbacks("request received and response sent", oRequest = oLastReceivedRequest, oResponse = oResponse);
  
  @ShowDebugOutput
  def __fSendMessage(oSelf, oMessage):
    # Serialize and send the cHTTPMessage instance.
    # Optionally close the connection if the message indicates this, even if an exception is thrown
    # Can throw timeout, shutdown or disconnected exception.
    sbMessage = oMessage.fsbSerialize();
    try:
      oSelf.fWriteBytes(sbMessage);
    except:
      raise;
    else:
      fShowDebugOutput("%s sent to %s." % (oMessage, oSelf));
      if gbDebugOutputFullHTTPMessages:
        fShowDebugOutput(str(sbMessage, 'latin1'));
      oSelf.fFireCallbacks("message sent", oMessage);
    finally:
      if oMessage.bCloseConnection:
        oSelf.fShutdownForWriting();
  
  # Read HTTP Messages
  @ShowDebugOutput
  def foReceiveRequest(oSelf,
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided, u0zMaxHeaderValueSize = zNotProvided, u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided, u0zMaxChunkSize = zNotProvided, u0zMaxNumberOfChunks = zNotProvided, # throw exception if more than this many chunks are received
    bStrictErrorChecking = True,
  ):
    # Attempt to receive a request from the connection.
    # If an exception is thrown, a transaction started here will be ended again.
    # Return None if an optional transaction could not be started.
    # Returns a cHTTPRequest object if a request was received.
    # Can throw timeout, shutdown or disconnected exception.
    try:
      oRequest = oSelf.__foReceiveMessage(
        # it's ok if a connection is dropped by a client before a request is received, so the above can return None.
        cHTTPRequest, 
        u0zMaxStatusLineSize = u0zMaxStatusLineSize,
        u0zMaxHeaderNameSize = u0zMaxHeaderNameSize, u0zMaxHeaderValueSize = u0zMaxHeaderValueSize, u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
        u0zMaxBodySize = u0zMaxBodySize, u0zMaxChunkSize = u0zMaxChunkSize, u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
        u0MaxNumberOfChunksBeforeDisconnecting = None,
        bStrictErrorChecking = bStrictErrorChecking,
      );
      oSelf.fFireCallbacks("request received", oRequest = oRequest);
      oSelf.__o0LastReceivedRequest = oRequest;
      return oRequest;
    except Exception as oException:
      raise;
  @ShowDebugOutput
  def foReceiveResponse(oSelf,
    u0zMaxStatusLineSize = None,
    u0zMaxHeaderNameSize = None, u0zMaxHeaderValueSize = None, u0zMaxNumberOfHeaders = None,
    u0zMaxBodySize = None, u0zMaxChunkSize = None, u0zMaxNumberOfChunks = None, # throw exception if more than this many chunks are received
    u0MaxNumberOfChunksBeforeDisconnecting = None, # disconnect and return response once this many chunks are received.
    bStrictErrorChecking = True,
  ):
    # Attempt to receive a response from the connection.
    # Optionally end a transaction after doing so, even if an exception is thrown.
    # Returns a cHTTPResponse object.
    # Can throw timeout, shutdown or disconnected exception.
    assert oSelf.bInTransaction, \
        "A transaction must be started before a response can be received over this connection.";
    oResponse = oSelf.__foReceiveMessage(
      # it's not ok if a connection is dropped by a server before a response is received, so the above cannot return None.
      cHTTPResponse, 
      u0zMaxStatusLineSize = u0zMaxStatusLineSize,
      u0zMaxHeaderNameSize = u0zMaxHeaderNameSize, u0zMaxHeaderValueSize = u0zMaxHeaderValueSize, u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
      u0zMaxBodySize = u0zMaxBodySize, u0zMaxChunkSize = u0zMaxChunkSize, u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
      u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
      bStrictErrorChecking = bStrictErrorChecking,
    );
    oSelf.fFireCallbacks("response received", oResponse = oResponse);
    oSelf.fFireCallbacks("request sent and response received", oRequest = oSelf.__o0LastSentRequest, oResponse = oResponse);
    oSelf.__o0LastSentRequest = None;
    return oResponse;
  
  @ShowDebugOutput
  def __foReceiveMessage(oSelf,
    cHTTPMessage,
    u0zMaxStatusLineSize,
    u0zMaxHeaderNameSize,
    u0zMaxHeaderValueSize,
    u0zMaxNumberOfHeaders,
    u0zMaxBodySize,
    u0zMaxChunkSize,
    u0zMaxNumberOfChunks,
    u0MaxNumberOfChunksBeforeDisconnecting,
    bStrictErrorChecking,
  ):
    # Read and parse a HTTP message.
    # Returns a cHTTPMessage instance.
    # Can throw timeout, shutdown or disconnected exception.
    u0MaxStatusLineSize  = fxGetFirstProvidedValue(u0zMaxStatusLineSize,   oSelf.u0DefaultMaxReasonPhraseSize);
    u0MaxHeaderNameSize  = fxGetFirstProvidedValue(u0zMaxHeaderNameSize,   oSelf.u0DefaultMaxHeaderNameSize);
    u0MaxHeaderValueSize = fxGetFirstProvidedValue(u0zMaxHeaderValueSize,  oSelf.u0DefaultMaxHeaderValueSize);
    u0MaxNumberOfHeaders = fxGetFirstProvidedValue(u0zMaxNumberOfHeaders,  oSelf.u0DefaultMaxNumberOfHeaders);
    u0MaxBodySize        = fxGetFirstProvidedValue(u0zMaxBodySize,         oSelf.u0DefaultMaxBodySize);
    u0MaxChunkSize       = fxGetFirstProvidedValue(u0zMaxChunkSize,        oSelf.u0DefaultMaxChunkSize);
    u0MaxNumberOfChunks  = fxGetFirstProvidedValue(u0zMaxNumberOfChunks,   oSelf.u0DefaultMaxNumberOfChunks);
    try:
      # Read and parse status line
      dxConstructorStatusLineArguments = oSelf.__fdxReadAndParseStatusLine(
        cHTTPMessage,
        u0MaxStatusLineSize,
        bStrictErrorChecking,
      );
      
      # Read and parse headers
      o0Headers = oSelf.__fo0ReadAndParseHeaders(
        cHTTPMessage,
        u0MaxHeaderNameSize,
        u0MaxHeaderValueSize,
        u0MaxNumberOfHeaders,
        bStrictErrorChecking,
      );
      # Find out what headers are present and at the same time do some sanity checking:
      # (this can throw a cHTTPInvalidMessageException if multiple Content-Length headers exist with different values)
      o0ContentLengthHeader = o0Headers and o0Headers.fo0GetUniqueHeaderForName(b"Content-Length");
      bTransferEncodingChunkedHeaderPresent = o0Headers and o0Headers.fbHasUniqueValueForName(b"Transfer-Encoding", b"Chunked");
      bConnectionCloseHeaderPresent = o0Headers and o0Headers.fbHasUniqueValueForName(b"Connection", b"Close");
      sb0Body = None;
      a0sbBodyChunks = None;
      o0AdditionalHeaders = None;
      
      # Parse Content-Length header value if any
      if o0ContentLengthHeader is None:
        u0ContentLengthHeaderValue = None;
      else:
        try:
          u0ContentLengthHeaderValue = int(o0ContentLengthHeader.sbValue);
          if u0ContentLengthHeaderValue < 0:
            raise ValueError("Content-Length value %s results in content length %s!?" % (o0ContentLengthHeader.sbValue, u0ContentLengthHeaderValue));
        except ValueError:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was invalid.",
            o0Connection = oSelf,
            dxDetails = {"sbContentLengthHeaderValue": o0ContentLengthHeader.sbValue},
          );
        if u0MaxBodySize is not None and u0ContentLengthHeaderValue > u0MaxBodySize:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was too large.",
            o0Connection = oSelf,
            dxDetails = {"uContentLengthHeaderValue": u0ContentLengthHeaderValue, "uMaxBodySize": u0MaxBodySize},
          );
      
      # Read and decode/decompress body
      if bTransferEncodingChunkedHeaderPresent:
        # Having both Content-Length and Transfer-Encoding: chunked headers is really weird but AFAICT not illegal.
        a0sbBodyChunks, bDisconnected = oSelf.__fxReadAndParseBodyChunks(
          cHTTPMessage,
          u0MaxBodySize,
          u0MaxChunkSize,
          u0MaxNumberOfChunks,
          u0MaxNumberOfChunksBeforeDisconnecting,
          u0ContentLengthHeaderValue,
        );
        if not bDisconnected:
          # More "headers" may follow.
          o0AdditionalHeaders = oSelf.__fo0ReadAndParseHeaders(
            cHTTPMessage,
            u0MaxHeaderNameSize,
            u0MaxHeaderValueSize,
            u0MaxNumberOfHeaders,
            bStrictErrorChecking,
          );
          if o0AdditionalHeaders:
            for sbIllegalHeaderName in [b"Transfer-Encoding", b"Content-Length"]:
              o0IllegalHeader = o0AdditionalHeaders.fo0GetUniqueHeaderForName(sbIllegalHeaderName);
              if o0IllegalHeader is not None:
                raise cHTTPInvalidMessageException(
                  "The message was not valid because it contained a %s header after the chunked body." % sbIllegalHeaderName,
                  o0Connection = oSelf,
                  dxDetails = {"oIllegalHeader": o0IllegalHeader},
                );
      elif u0ContentLengthHeaderValue is not None:
        fShowDebugOutput("Reading %d bytes response body..." % u0ContentLengthHeaderValue);
        sb0Body = oSelf.fsbReadBytes(u0ContentLengthHeaderValue);
      elif bConnectionCloseHeaderPresent and issubclass(cHTTPMessage, cHTTPResponse):
        # A request with a "Connection: Close" header cannot have a body, as closing the
        # connection after sending it would prevent the client from seeing the response.
        fShowDebugOutput("Reading response body until disconnected...");
        sb0Body = oSelf.fsbReadBytesUntilDisconnected(u0MaxNumberOfBytes = u0MaxBodySize);
      else:
        fShowDebugOutput("No response body expected.");
      oMessage = cHTTPMessage(
        o0zHeaders = o0Headers,
        sb0Body = sb0Body,
        a0sbBodyChunks = a0sbBodyChunks,
        o0AdditionalHeaders = o0AdditionalHeaders,
        **dxConstructorStatusLineArguments
      );
      fShowDebugOutput("%s received from %s." % (oMessage, oSelf));
      if gbDebugOutputFullHTTPMessages:
        fShowDebugOutput(str(oMessage.fsbSerialize(), 'latin1'));
      
      if oMessage.bCloseConnection:
        fShowDebugOutput("Closing connection per message headers...");
        oSelf.fDisconnect();
      
      oSelf.fFireCallbacks("message received", oMessage);
      
      return oMessage;
    except cHTTPInvalidMessageException:
      # When an invalid message is detected, we disconnect because we cannot
      # guarantee we can interpret the data correctly anymore.
      oSelf.fDisconnect();
      raise;
  
  @ShowDebugOutput
  def __fdxReadAndParseStatusLine(oSelf,
    cHTTPMessage,
    u0MaxStatusLineSize,
    bStrictErrorChecking,
  ):
    fShowDebugOutput("Reading status line...");
    sb0StatusLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxStatusLineSize);
    if sb0StatusLineCRLF is None:
      sbStatusLine = oSelf.fsbReadBufferedData();
      raise cHTTPInvalidMessageException(
        "The status line was too large.",
        o0Connection = oSelf,
        dxDetails = {"sbStatusLine": sbStatusLine, "u0MaxStatusLineSize": u0MaxStatusLineSize},
      );
    fShowDebugOutput("Parsing status line...");
    return cHTTPMessage.fdxParseStatusLine(sb0StatusLineCRLF[:-2], o0Connection = oSelf, bStrictErrorChecking = bStrictErrorChecking);
  
  @ShowDebugOutput
  def __fo0ReadAndParseHeaders(oSelf,
    cHTTPMessage,
    u0MaxHeaderNameSize,
    u0MaxHeaderValueSize,
    u0MaxNumberOfHeaders,
    bStrictErrorChecking,
  ):
    fShowDebugOutput("Reading headers...");
    if u0MaxHeaderNameSize is None or u0MaxHeaderValueSize is None:
      u0MaxHeaderLineSize = None;
    else:
      u0MaxHeaderLineSize = u0MaxHeaderNameSize + 2 + u0MaxHeaderValueSize;
    asbHeaderLines = [];
    while 1:
      sb0HeaderLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxHeaderLineSize);
      if sb0HeaderLineCRLF is None:
        sbHeaderLine = oSelf.fsbReadBufferedData();
        raise cHTTPInvalidMessageException(
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
    return cHTTPMessage.foParseHeaderLines(asbHeaderLines, o0Connection = oSelf, bStrictErrorChecking = bStrictErrorChecking);
  
  @ShowDebugOutput
  def __fxReadAndParseBodyChunks(oSelf,
    cHTTPMessage,
    u0MaxBodySize,
    u0MaxChunkSize,
    u0MaxNumberOfChunks,
    u0MaxNumberOfChunksBeforeDisconnecting,
    u0ContentLengthHeaderValue,
  ):
    if u0ContentLengthHeaderValue is not None:
      uContentLengthHeaderValue = u0ContentLengthHeaderValue;
      fShowDebugOutput("Reading chunked response body WITH Content-Length = %d..." % uContentLengthHeaderValue);
    else:
      fShowDebugOutput("Reading chunked response body...");
    asbBodyChunks = [];
    uTotalNumberOfBodyChunkBytes = 0;
    uTotalNumberOfBodyBytesInChunks = 0;
    while 1:
      if u0MaxNumberOfChunksBeforeDisconnecting is not None:
        uMaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting;
        if len(asbBodyChunks) == uMaxNumberOfChunksBeforeDisconnecting:
          oSelf.fDisconnect();
          return (asbBodyChunks, True);
      if u0MaxNumberOfChunks is not None:
        uMaxNumberOfChunks = u0MaxNumberOfChunks;
        if len(asbBodyChunks) == uMaxNumberOfChunks:
          raise cHTTPInvalidMessageException(
            "There are too many body chunks.",
            o0Connection = oSelf,
            dxDetails = {"uMaxNumberOfChunks": uMaxNumberOfChunks},
          );
      fShowDebugOutput("Reading response body chunk #%d header line..." % (len(asbBodyChunks) + 1));
      # Read size in the chunk header
      u0MaxChunkHeaderLineSize = oSelf.u0MaxChunkSizeCharacters + 2 if oSelf.u0MaxChunkSizeCharacters is not None else None;
      if u0ContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + 5; # minimum is "0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            o0Connection = oSelf,
            dxDetails = {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
        if (
          u0MaxNumberOfBytesInBodyRemaining is not None
          and u0MaxChunkHeaderLineSize is not None
          and u0MaxNumberOfBytesInBodyRemaining < u0MaxChunkHeaderLineSize
        ):
          u0MaxChunkHeaderLineSize = u0MaxNumberOfBytesInBodyRemaining;
      sb0ChunkHeaderLineCRLF = oSelf.fsb0ReadUntilMarker(b"\r\n", u0MaxNumberOfBytes = u0MaxChunkHeaderLineSize);
      if sb0ChunkHeaderLineCRLF is None:
        sbChunkHeaderLine = oSelf.fsbReadBufferedData();
        raise cHTTPInvalidMessageException(
          "A body chunk header line was too large.",
          o0Connection = oSelf,
          dxDetails = {"sbChunkHeaderLine": sbChunkHeaderLine, "uMaxChunkHeaderLineSize": u0MaxChunkHeaderLineSize},
        );
      uTotalNumberOfBodyChunkBytes += len(sb0ChunkHeaderLineCRLF);
      sbChunkHeaderLine = sb0ChunkHeaderLineCRLF[:-2];
      if b";" in sbChunkHeaderLine:
        raise cHTTPInvalidMessageException(
          "A body chunk header line contained an extension, which is not currently supported.",
          o0Connection = oSelf,
          dxDetails = {"sbChunkHeaderLine": sbChunkHeaderLine},
        );
      try:
        uChunkSize = int(sbChunkHeaderLine, 16);
      except ValueError:
        raise cHTTPInvalidMessageException(
          "A body chunk header line contained an invalid character in the chunk size.",
          o0Connection = oSelf,
          dxDetails = {"sbChunkHeaderLine": sbChunkHeaderLine},
        );
      if uChunkSize == 0:
        break;
      if u0ContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + uChunkSize + 2 + 7; # minimum after this chunk is "\r\n"+"0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            o0Connection = oSelf,
            dxDetails = {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
      if u0MaxChunkSize is not None:
        uMaxChunkSize = u0MaxChunkSize;
        if uChunkSize > uMaxChunkSize:
          raise cHTTPInvalidMessageException(
            "A body chunk was too large.",
            o0Connection = oSelf,
            dxDetails = {"uMaxChunkSize": uMaxChunkSize, "uChunkSize": uChunkSize},
          );
      # Check chunk size and number of chunks
      uTotalNumberOfBodyBytesInChunks += uChunkSize;
      if u0MaxBodySize is not None:
        uMaxBodySize = u0MaxBodySize;
        if uTotalNumberOfBodyBytesInChunks > uMaxBodySize:
          raise cHTTPInvalidMessageException(
            "There are too many bytes in the body chunks.",
            o0Connection = oSelf,
            dxDetails = {"uMaxBodySize": uMaxBodySize, "uMinimumNumberOfBodyBytesInBodyChunks": uTotalNumberOfBodyBytesInChunks},
          );
      # Read the chunk
      fShowDebugOutput("Reading response body chunk #%d (%d bytes)..." % (len(asbBodyChunks) + 1, uChunkSize));
      sbChunkCRLF = oSelf.fsbReadBytes(uChunkSize + 2);
      if sbChunkCRLF[-2:] != b"\r\n":
        raise cHTTPInvalidMessageException(
          "A body chunk did not end with CRLF.",
          o0Connection = oSelf,
          dxDetails = {"sbChunkCRLF": sbChunkCRLF},
        );
      uTotalNumberOfBodyChunkBytes += len(sbChunkCRLF);
      asbBodyChunks.append(sbChunkCRLF[:-2]);
    if u0ContentLengthHeaderValue is not None:
      if uTotalNumberOfBodyChunkBytes < uContentLengthHeaderValue:
        raise cHTTPInvalidMessageException(
          "There are less bytes in the body chunks than the Content-Length header indicated.",
          o0Connection = oSelf,
          dxDetails = {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uTotalNumberOfBodyChunkBytes": uTotalNumberOfBodyChunkBytes},
        );
    return (asbBodyChunks, False);
  
  @ShowDebugOutput
  def foSendRequestAndReceiveResponse(oSelf,
    # Send request arguments:
    oRequest,
    # Receive response arguments:
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided,
    u0zMaxHeaderValueSize = zNotProvided,
    u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided,
    u0zMaxChunkSize = zNotProvided,
    u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = None,
  ):
    oSelf.fSendRequest(oRequest);
    return oSelf.foReceiveResponse(
      u0zMaxStatusLineSize = u0zMaxStatusLineSize,
      u0zMaxHeaderNameSize = u0zMaxHeaderNameSize,
      u0zMaxHeaderValueSize = u0zMaxHeaderValueSize,
      u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
      u0zMaxBodySize = u0zMaxBodySize,
      u0zMaxChunkSize = u0zMaxChunkSize,
      u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
      u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
    );
  
for cException in acExceptions:
  setattr(cHTTPConnection, cException.__name__, cException);
