import re;

try: # mDebugOutput use is Optional
  from mDebugOutput import *;
except: # Do nothing if not available.
  ShowDebugOutput = lambda fxFunction: fxFunction;
  fShowDebugOutput = lambda sMessage: None;
  fEnableDebugOutputForModule = lambda mModule: None;
  fEnableDebugOutputForClass = lambda cClass: None;
  fEnableAllDebugOutput = lambda: None;
  cCallStack = fTerminateWithException = fTerminateWithConsoleOutput = None;

from mTCPIPConnections import cTransactionalBufferedTCPIPConnection;
from mHTTPProtocol import cHTTPRequest, cHTTPResponse, iHTTPMessage;

from .mExceptions import *;
from .mNotProvided import *;

gbDebugOutputFullHTTPMessages = False;

class cHTTPConnection(cTransactionalBufferedTCPIPConnection):
  u0DefaultMaxReasonPhraseSize = 1000;
  u0DefaultMaxHeaderNameSize = 10*1000;
  u0DefaultMaxHeaderValueSize = 10*1000;
  u0DefaultMaxNumberOfHeaders = 256;
  u0DefaultMaxBodySize = 1000*1000*1000;
  u0DefaultMaxChunkSize = 10*1000*1000;
  u0DefaultMaxNumberOfChunks = 1000*1000;
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
      "request sent", "request received", 
      "response sent", "response received",
    );
  
  # Send HTTP Messages
  @ShowDebugOutput
  def fbSendRequest(oSelf, oRequest, bStartTransaction = True, n0TransactionTimeoutInSeconds = None):
    # Attempt to write a request to the connection.
    # Optionally start a transaction before doing so.
    # If an exception is thrown, a transaction started here will be ended again.
    # The connection must not be shut down for reading or an exception will be thrown.
    # return False if an optional transaction could not be started.
    # return True if the request was sent.
    # Can throw timeout, out-of-band-data, shutdown or disconnected exception.
    if bStartTransaction and not oSelf.fbStartTransaction(n0TransactionTimeoutInSeconds):
      # The connection is stopping or disconnected; the request will not be sent.
      return False;
    try:
      # The server should only send data in response to a request; if it sent out-of-band data we close the connection.
      sOutOfBandData = oSelf.fsReadAvailableBytes();
      if sOutOfBandData:
        # The server sent out-of-band data; close the connection and raise an exception.
        oSelf.fDisconnect();
        raise cHTTPOutOfBandDataException(
          "Out-of-band data was received before request was sent!",
          sOutOfBandData,
        );
      oSelf.__fSendMessage(oRequest);
      oSelf.fFireCallbacks("request sent", oRequest);
      return True;
    except Exception as oException:
      if bStartTransaction: oSelf.fEndTransaction();
      raise;
  
  @ShowDebugOutput
  def fSendResponse(oSelf, oResponse, bEndTransaction = True):
    # Attempt to write a response to the connection.
    # Optionally end a transaction after doing so, even if an exception is thrown.
    # Can throw timeout, shutdown or disconnected exception.
    try:
      oSelf.__fSendMessage(oResponse);
      oSelf.fFireCallbacks("response sent", oResponse);
    finally:
      if bEndTransaction: oSelf.fEndTransaction();
  
  @ShowDebugOutput
  def __fSendMessage(oSelf, oMessage):
    # Serialize and send the cHTTPMessage instance.
    # Optionally close the connection if the message indicates this, even if an exception is thrown
    # Can throw timeout, shutdown or disconnected exception.
    sMessage = oMessage.fsSerialize();
    try:
      oSelf.fWriteBytes(sMessage);
    except:
      raise;
    else:
      fShowDebugOutput("%s sent to %s." % (oMessage, oSelf));
      if gbDebugOutputFullHTTPMessages:
        fShowDebugOutput(oMessage.fsSerialize());
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
    bStartTransaction = True, n0TransactionTimeoutInSeconds = None,
  ):
    # Attempt to receive a request from the connection.
    # Optionally start a transaction before doing so.
    # If an exception is thrown, a transaction started here will be ended again.
    # Return None if an optional transaction could not be started.
    # Returns a cHTTPRequest object if a request was received.
    # Can throw timeout, shutdown or disconnected exception.
    if bStartTransaction and not oSelf.fbStartTransaction(n0TransactionTimeoutInSeconds):
      # Another transaction is active
      return None;
    try:
      oRequest = oSelf.__foReceiveMessage(
        # it's ok if a connection is dropped by a client before a request is received, so the above can return None.
        cHTTPRequest, 
        u0zMaxStatusLineSize = u0zMaxStatusLineSize,
        u0zMaxHeaderNameSize = u0zMaxHeaderNameSize, u0zMaxHeaderValueSize = u0zMaxHeaderValueSize, u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
        u0zMaxBodySize = u0zMaxBodySize, u0zMaxChunkSize = u0zMaxChunkSize, u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
        u0MaxNumberOfChunksBeforeDisconnecting = None,
      );
      oSelf.fFireCallbacks("request received", oRequest);
      return oRequest;
    except Exception as oException:
      if bStartTransaction: oSelf.fEndTransaction();
      raise;
  
  @ShowDebugOutput
  def foReceiveResponse(oSelf,
    u0zMaxStatusLineSize = None,
    u0zMaxHeaderNameSize = None, u0zMaxHeaderValueSize = None, u0zMaxNumberOfHeaders = None,
    u0zMaxBodySize = None, u0zMaxChunkSize = None, u0zMaxNumberOfChunks = None, # throw exception if more than this many chunks are received
    u0MaxNumberOfChunksBeforeDisconnecting = None, # disconnect and return response once this many chunks are received.
    bEndTransaction = True,
  ):
    # Attempt to receive a response from the connection.
    # Optionally end a transaction after doing so, even if an exception is thrown.
    # Returns a cHTTPResponse object.
    # Can throw timeout, shutdown or disconnected exception.
    assert oSelf.bInTransaction, \
        "A transaction must be started before a response can be received over this connection.";
    try:
      oResponse = oSelf.__foReceiveMessage(
        # it's not ok if a connection is dropped by a server before a response is received, so the above cannot return None.
        cHTTPResponse, 
        u0zMaxStatusLineSize = u0zMaxStatusLineSize,
        u0zMaxHeaderNameSize = u0zMaxHeaderNameSize, u0zMaxHeaderValueSize = u0zMaxHeaderValueSize, u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
        u0zMaxBodySize = u0zMaxBodySize, u0zMaxChunkSize = u0zMaxChunkSize, u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
        u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
      );
      oSelf.fFireCallbacks("response received", oResponse);
      return oResponse;
    finally:
      if bEndTransaction: oSelf.fEndTransaction();
  
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
      dxConstructorStatusLineArguments = oSelf.__fdxReadAndParseStatusLine(cHTTPMessage, u0MaxStatusLineSize);
      
      # Read and parse headers
      o0Headers = oSelf.__fo0ReadAndParseHeaders(cHTTPMessage, u0MaxHeaderNameSize, u0MaxHeaderValueSize, u0MaxNumberOfHeaders);
      # Find out what headers are present and at the same time do some sanity checking:
      # (this can throw a cHTTPInvalidMessageException if multiple Content-Length headers exist with different values)
      o0ContentLengthHeader = o0Headers and o0Headers.fo0GetUniqueHeaderForName("Content-Length");
      bTransferEncodingChunkedHeaderPresent = o0Headers and o0Headers.fbHasUniqueValueForName("Transfer-Encoding", "Chunked");
      bConnectionCloseHeaderPresent = o0Headers and o0Headers.fbHasUniqueValueForName("Connection", "Close");
      s0Body = None;
      a0sBodyChunks = None;
      o0AdditionalHeaders = None;
      
      # Parse Content-Length header value if any
      if o0ContentLengthHeader is None:
        u0ContentLengthHeaderValue = None;
      else:
        try:
          u0ContentLengthHeaderValue = long(o0ContentLengthHeader.sValue);
          if u0ContentLengthHeaderValue < 0:
            raise ValueError("Content-Length value %s results in content length %s!?" % (o0ContentLengthHeader.sValue, u0ContentLengthHeaderValue));
        except ValueError:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was invalid.",
            {"o0ContentLengthHeader": o0ContentLengthHeader},
          );
        if u0MaxBodySize is not None and u0ContentLengthHeaderValue > u0MaxBodySize:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was too large.",
            {"o0ContentLengthHeader": o0ContentLengthHeader, "u0MaxBodySize": u0MaxBodySize},
          );
      
      # Read and decode/decompress body
      if bTransferEncodingChunkedHeaderPresent:
        # Having both Content-Length and Transfer-Encoding: chunked headers is really weird but AFAICT not illegal.
        a0sBodyChunks, bDisconnected = oSelf.__fxReadAndParseBodyChunks(
          cHTTPMessage,
          u0MaxBodySize,
          u0MaxChunkSize,
          u0MaxNumberOfChunks,
          u0MaxNumberOfChunksBeforeDisconnecting,
          u0ContentLengthHeaderValue,
        );
        if not bDisconnected:
          # More "headers" may follow.
          oAdditionalHeaders = oSelf.__foReadAndParseHeaders(cHTTPMessage, u0MaxHeaderNameSize, u0MaxHeaderValueSize, u0MaxNumberOfHeaders);
          for sIllegalName in ["Transfer-Encoding", "Content-Length"]:
            o0IllegalHeader = oAdditionalHeaders.fo0GetUniqueHeaderForName(sIllegalName);
            if o0IllegalHeader is not None:
              raise cHTTPInvalidMessageException(
                "The message was not valid because it contained a %s header after the chunked body." % sIllegalName,
                o0IllegalHeader.fsSerialize(),
              );
      elif u0ContentLengthHeaderValue is not None:
        fShowDebugOutput("Reading %d bytes response body..." % u0ContentLengthHeaderValue);
        s0Body = oSelf.fsReadBytes(u0ContentLengthHeaderValue);
      elif bConnectionCloseHeaderPresent:
        fShowDebugOutput("Reading response body until disconnected...");
        s0Body = oSelf.fsReadBytesUntilDisconnected(u0MaxNumberOfBytes = u0MaxBodySize);
      else:
        fShowDebugOutput("No response body expected.");
      oMessage = cHTTPMessage(
        o0zHeaders = o0Headers,
        s0Body = s0Body,
        a0sBodyChunks = a0sBodyChunks,
        o0AdditionalHeaders = o0AdditionalHeaders,
        **dxConstructorStatusLineArguments
      );
      fShowDebugOutput("%s received from %s." % (oMessage, oSelf));
      if gbDebugOutputFullHTTPMessages:
        fShowDebugOutput(oMessage.fsSerialize());
      
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
  ):
    fShowDebugOutput("Reading status line...");
    s0StatusLineCRLF = oSelf.fs0ReadUntilMarker("\r\n", u0MaxNumberOfBytes = u0MaxStatusLineSize);
    if s0StatusLineCRLF is None:
      sStatusLine = oSelf.fsReadBufferedData();
      raise cHTTPInvalidMessageException(
        "The status line was too large.",
        {"sStatusLine": sStatusLine, "len(sStatusLine)<at least>": len(sStatusLine), "u0MaxStatusLineSize": u0MaxStatusLineSize},
      );
    fShowDebugOutput("Parsing status line...");
    return cHTTPMessage.fdxParseStatusLine(s0StatusLineCRLF[:-2]);
  
  @ShowDebugOutput
  def __fo0ReadAndParseHeaders(oSelf,
    cHTTPMessage,
    u0MaxHeaderNameSize,
    u0MaxHeaderValueSize,
    u0MaxNumberOfHeaders,
  ):
    fShowDebugOutput("Reading headers...");
    if u0MaxHeaderNameSize is None or u0MaxHeaderValueSize is None:
      u0MaxHeaderLineSize = None;
    else:
      u0MaxHeaderLineSize = u0MaxHeaderNameSize + 2 + u0MaxHeaderValueSize;
    asHeaderLines = [];
    while 1:
      s0HeaderLineCRLF = oSelf.fs0ReadUntilMarker("\r\n", u0MaxNumberOfBytes = u0MaxHeaderLineSize);
      if s0HeaderLineCRLF is None:
        sHeaderLine = oSelf.fsReadBufferedData();
        raise cHTTPInvalidMessageException(
          "A hreader line was too large.",
          {"sHeaderLine": sHeaderLine, "len(sHeaderLine)<at least>": len(sHeaderLine), "u0MaxHeaderLineSize": u0MaxHeaderLineSize},
        );
      sHeaderLine = s0HeaderLineCRLF[:-2];
      if len(sHeaderLine) == 0:
        break; # Empty line == end of headers
      asHeaderLines.append(sHeaderLine);
    if len(asHeaderLines) == 0:
      return None;
    return cHTTPMessage.foParseHeaderLines(asHeaderLines);
  
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
    asBodyChunks = [];
    uTotalNumberOfBodyChunkBytes = 0;
    uTotalNumberOfBodyBytesInChunks = 0;
    while 1:
      if u0MaxNumberOfChunksBeforeDisconnecting is not None:
        uMaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting;
        if len(asBodyChunks) == uMaxNumberOfChunksBeforeDisconnecting:
          oSelf.fDisconnect();
          return (asBodyChunks, True);
      if u0MaxNumberOfChunks is not None:
        uMaxNumberOfChunks = u0MaxNumberOfChunks;
        if len(asBodyChunks) == uMaxNumberOfChunks:
          raise cHTTPInvalidMessageException(
            "There are too many body chunks.",
            {"uMaxNumberOfChunks": uMaxNumberOfChunks},
          );
      fShowDebugOutput("Reading response body chunk #%d header line..." % (len(asBodyChunks) + 1));
      # Read size in the chunk header
      u0MaxChunkHeaderLineSize = oSelf.u0MaxChunkSizeCharacters + 2 if oSelf.u0MaxChunkSizeCharacters is not None else None;
      if u0ContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + 5; # minimum is "0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
        if (
          u0MaxNumberOfBytesInBodyRemaining is not None
          and u0MaxChunkHeaderLineSize is not None
          and u0MaxNumberOfBytesInBodyRemaining < u0MaxChunkHeaderLineSize
        ):
          u0MaxChunkHeaderLineSize = u0MaxNumberOfBytesInBodyRemaining;
      s0ChunkHeaderLineCRLF = oSelf.fs0ReadUntilMarker("\r\n", u0MaxNumberOfBytes = u0MaxChunkHeaderLineSize);
      if s0ChunkHeaderLineCRLF is None:
        sChunkHeaderLine = oSelf.fsReadBufferedData();
        raise cHTTPInvalidMessageException(
          "A body chunk header line was too large.",
          {"sChunkHeaderLine": sChunkHeaderLine, "uMaxChunkHeaderLineSize": u0MaxChunkHeaderLineSize},
        );
      uTotalNumberOfBodyChunkBytes += len(s0ChunkHeaderLineCRLF);
      sChunkHeaderLine = s0ChunkHeaderLineCRLF[:-2];
      if ";" in sChunkHeaderLine:
        raise cHTTPInvalidMessageException(
          "A body chunk header line contained an extension, which is not currently supported.",
          {"sChunkHeaderLine": sChunkHeaderLine},
        );
      try:
        uChunkSize = long(sChunkHeaderLine, 16);
      except ValueError:
        raise cHTTPInvalidMessageException(
          "A body chunk header line contained an invalid character in the chunk size.",
          {"sChunkHeaderLine": sChunkHeaderLine},
        );
      if uChunkSize == 0:
        break;
      if u0ContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + uChunkSize + 2 + 7; # minimum after this chunk is "\r\n"+"0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
      if u0MaxChunkSize is not None:
        uMaxChunkSize = u0MaxChunkSize;
        if uChunkSize > uMaxChunkSize:
          raise cHTTPInvalidMessageException(
            "A body chunk was too large.",
            {"uMaxChunkSize": uMaxChunkSize, "uChunkSize": uChunkSize},
          );
      # Check chunk size and number of chunks
      uTotalNumberOfBodyBytesInChunks += uChunkSize;
      if u0MaxBodySize is not None:
        uMaxBodySize = u0MaxBodySize;
        if uTotalNumberOfBodyBytesInChunks > uMaxBodySize:
          raise cHTTPInvalidMessageException(
            "There are too many bytes in the body chunks.",
            {"uMaxBodySize": uMaxBodySize, "uMinimumNumberOfBodyBytesInBodyChunks": uTotalNumberOfBodyBytesInChunks},
          );
      # Read the chunk
      fShowDebugOutput("Reading response body chunk #%d (%d bytes)..." % (len(asBodyChunks) + 1, uChunkSize));
      sChunkCRLF = oSelf.fsReadBytes(uChunkSize + 2);
      if sChunkCRLF[-2:] != "\r\n":
        raise cHTTPInvalidMessageException(
          "A body chunk did not end with CRLF.",
          {"sChunkCRLF": sChunkCRLF},
        );
      uTotalNumberOfBodyChunkBytes += len(sChunkCRLF);
      asBodyChunks.append(sChunkCRLF[:-2]);
    if u0ContentLengthHeaderValue is not None:
      if uTotalNumberOfBodyChunkBytes < uContentLengthHeaderValue:
        raise cHTTPInvalidMessageException(
          "There are less bytes in the body chunks than the Content-Length header indicated.",
          {"uContentLengthHeaderValue": uContentLengthHeaderValue, "uTotalNumberOfBodyChunkBytes": uTotalNumberOfBodyChunkBytes},
        );
    return (asBodyChunks, False);

  @ShowDebugOutput
  def fo0SendRequestAndReceiveResponse(oSelf,
    # Send request arguments:
    oRequest, bStartTransaction = True,
    # Receive response arguments:
    u0zMaxStatusLineSize = zNotProvided,
    u0zMaxHeaderNameSize = zNotProvided,
    u0zMaxHeaderValueSize = zNotProvided,
    u0zMaxNumberOfHeaders = zNotProvided,
    u0zMaxBodySize = zNotProvided,
    u0zMaxChunkSize = zNotProvided,
    u0zMaxNumberOfChunks = zNotProvided,
    u0MaxNumberOfChunksBeforeDisconnecting = None,
    bEndTransaction = True,
  ):
    if not oSelf.fbSendRequest(oRequest, bStartTransaction = bStartTransaction):
      if not bStartTransaction and bEndTransaction:
        # If we were asked not to start a transaction but we were tasked to
        # end it we should do so:
        oSelf.fEndTransaction();
      return None;
    return oSelf.foReceiveResponse(
      u0zMaxStatusLineSize = u0zMaxStatusLineSize,
      u0zMaxHeaderNameSize = u0zMaxHeaderNameSize,
      u0zMaxHeaderValueSize = u0zMaxHeaderValueSize,
      u0zMaxNumberOfHeaders = u0zMaxNumberOfHeaders,
      u0zMaxBodySize = u0zMaxBodySize,
      u0zMaxChunkSize = u0zMaxChunkSize,
      u0zMaxNumberOfChunks = u0zMaxNumberOfChunks,
      u0MaxNumberOfChunksBeforeDisconnecting = u0MaxNumberOfChunksBeforeDisconnecting,
      bEndTransaction = bEndTransaction,
    );
  
