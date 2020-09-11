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

gbDebugOutputFullHTTPMessages = False;

class cHTTPConnection(cTransactionalBufferedTCPIPConnection):
  uzDefaultMaxReasonPhraseSize = 1000;
  uzDefaultMaxHeaderNameSize = 10*1000;
  uzDefaultMaxHeaderValueSize = 10*1000;
  uzDefaultMaxNumberOfHeaders = 256;
  uzDefaultMaxBodySize = 10*1000*1000;
  uzDefaultMaxChunkSize = 10*1000*1000;
  uzDefaultMaxNumberOfChunks = 1000*1000;
  # The HTTP RFC does not provide an upper limit to the maximum number of characters a chunk size can contain.
  # So, by padding a valid chunk size on the left with "0", one could theoretically create a valid chunk header that has
  # an infinite size. To prevent us accepting such an obviously invalid value, we will accept no chunk size containing
  # more than 16 chars (i.e. 64-bit numbers).
  uzMaxChunkSizeCharacters = 16;
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
  def fbSendRequest(oSelf, oRequest, bStartTransaction = True, nzTransactionTimeoutInSeconds = None):
    # Attempt to write a request to the connection.
    # Optionally start a transaction before doing so.
    # If an exception is thrown, a transaction started here will be ended again.
    # The connection must not be shut down for reading or an exception will be thrown.
    # return False if an optional transaction could not be started.
    # return True if the request was sent.
    # Can throw timeout, out-of-band-data, shutdown or disconnected exception.
    if bStartTransaction and not oSelf.fbStartTransaction(nzTransactionTimeoutInSeconds):
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
    uzMaxStatusLineSize = None,
    uzMaxHeaderNameSize = None, uzMaxHeaderValueSize = None, uzMaxNumberOfHeaders = None,
    uzMaxBodySize = None, uzMaxChunkSize = None, uzMaxNumberOfChunks = None, # throw exception if more than this many chunks are received
    bStartTransaction = True, nzTransactionTimeoutInSeconds = None,
  ):
    # Attempt to receive a request from the connection.
    # Optionally start a transaction before doing so.
    # If an exception is thrown, a transaction started here will be ended again.
    # Return None if an optional transaction could not be started.
    # Returns a cHTTPRequest object if a request was received.
    # Can throw timeout, shutdown or disconnected exception.
    if bStartTransaction and not oSelf.fbStartTransaction(nzTransactionTimeoutInSeconds):
      # Another transaction is active
      return None;
    try:
      oRequest = oSelf.__foReceiveMessage(
        # it's ok if a connection is dropped by a client before a request is received, so the above can return None.
        cHTTPRequest, 
        uzMaxStatusLineSize = uzMaxStatusLineSize,
        uzMaxHeaderNameSize = uzMaxHeaderNameSize, uzMaxHeaderValueSize = uzMaxHeaderValueSize, uzMaxNumberOfHeaders = uzMaxNumberOfHeaders,
        uzMaxBodySize = uzMaxBodySize, uzMaxChunkSize = uzMaxChunkSize, uzMaxNumberOfChunks = uzMaxNumberOfChunks,
        uzMaximumNumberOfChunksBeforeDisconnecting = None,
      );
      oSelf.fFireCallbacks("request received", oRequest);
      return oRequest;
    except Exception as oException:
      if bStartTransaction: oSelf.fEndTransaction();
      raise;
  
  @ShowDebugOutput
  def foReceiveResponse(oSelf,
    uzMaxStatusLineSize = None,
    uzMaxHeaderNameSize = None, uzMaxHeaderValueSize = None, uzMaxNumberOfHeaders = None,
    uzMaxBodySize = None, uzMaxChunkSize = None, uzMaxNumberOfChunks = None, # throw exception if more than this many chunks are received
    uzMaximumNumberOfChunksBeforeDisconnecting = None, # disconnect and return response once this many chunks are received.
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
        uzMaxStatusLineSize = uzMaxStatusLineSize,
        uzMaxHeaderNameSize = uzMaxHeaderNameSize, uzMaxHeaderValueSize = uzMaxHeaderValueSize, uzMaxNumberOfHeaders = uzMaxNumberOfHeaders,
        uzMaxBodySize = uzMaxBodySize, uzMaxChunkSize = uzMaxChunkSize, uzMaxNumberOfChunks = uzMaxNumberOfChunks,
        uzMaximumNumberOfChunksBeforeDisconnecting = uzMaximumNumberOfChunksBeforeDisconnecting,
      );
      oSelf.fFireCallbacks("response received", oResponse);
      return oResponse;
    finally:
      if bEndTransaction: oSelf.fEndTransaction();
  
  @ShowDebugOutput
  def __foReceiveMessage(oSelf,
    cHTTPMessage,
    uzMaxStatusLineSize,
    uzMaxHeaderNameSize, uzMaxHeaderValueSize, uzMaxNumberOfHeaders,
    uzMaxBodySize, uzMaxChunkSize, uzMaxNumberOfChunks,
    uzMaximumNumberOfChunksBeforeDisconnecting,
  ):
    # Read and parse a HTTP message.
    # Returns a cHTTPMessage instance.
    # Can throw timeout, shutdown or disconnected exception.
    uzMaxStatusLineSize  = uzMaxStatusLineSize  if uzMaxStatusLineSize   is not None else oSelf.uzDefaultMaxReasonPhraseSize;
    uzMaxHeaderNameSize  = uzMaxHeaderNameSize  if uzMaxHeaderNameSize   is not None else oSelf.uzDefaultMaxHeaderNameSize;
    uzMaxHeaderValueSize = uzMaxHeaderValueSize if uzMaxHeaderValueSize  is not None else oSelf.uzDefaultMaxHeaderValueSize;
    uzMaxNumberOfHeaders = uzMaxNumberOfHeaders if uzMaxNumberOfHeaders  is not None else oSelf.uzDefaultMaxNumberOfHeaders;
    uzMaxBodySize        = uzMaxBodySize        if uzMaxBodySize         is not None else oSelf.uzDefaultMaxBodySize;
    uzMaxChunkSize       = uzMaxChunkSize       if uzMaxChunkSize        is not None else oSelf.uzDefaultMaxChunkSize;
    uzMaxNumberOfChunks  = uzMaxNumberOfChunks  if uzMaxNumberOfChunks   is not None else oSelf.uzDefaultMaxNumberOfChunks;
    try:
      # Read and parse status line
      dxConstructorStatusLineArguments = oSelf.__fdxReadAndParseStatusLine(cHTTPMessage, uzMaxStatusLineSize);
      
      # Read and parse headers
      oHeaders = oSelf.__foReadAndParseHeaders(cHTTPMessage, uzMaxHeaderNameSize, uzMaxHeaderValueSize, uzMaxNumberOfHeaders);
      # Find out what headers are present and at the same time do some sanity checking:
      # (this can throw a cHTTPInvalidMessageException if multiple Content-Length headers exist with different values)
      ozContentLengthHeader = oHeaders.fozGetUniqueHeaderForName("Content-Length");
      bTransferEncodingChunkedHeaderPresent = oHeaders.fbHasUniqueValueForName("Transfer-Encoding", "Chunked");
      bConnectionCloseHeaderPresent = oHeaders.fbHasUniqueValueForName("Connection", "Close");
      szBody = None;
      azsBodyChunks = None;
      ozAdditionalHeaders = None;
      
      # Parse Content-Length header value if any
      if ozContentLengthHeader is None:
        uzContentLengthHeaderValue = None;
      else:
        try:
          uzContentLengthHeaderValue = long(ozContentLengthHeader.sValue);
          if uzContentLengthHeaderValue < 0:
            raise ValueError("Content-Length value %s results in content length %s!?" % (ozContentLengthHeader.sValue, uzContentLengthHeaderValue));
        except ValueError:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was invalid.",
            {"oContentLengthHeader": ozContentLengthHeader},
          );
        if uzMaxBodySize is not None and uzContentLengthHeaderValue > uzMaxBodySize:
          raise cHTTPInvalidMessageException(
            "The Content-Length header was too large.",
            {"oContentLengthHeader": ozContentLengthHeader, "uMaxBodySize": uzMaxBodySize},
          );
      
      # Read and decode/decompress body
      if bTransferEncodingChunkedHeaderPresent:
        # Having both Content-Length and Transfer-Encoding: chunked headers is really weird but AFAICT not illegal.
        azsBodyChunks, bDisconnected = oSelf.__fxReadAndParseBodyChunks(cHTTPMessage, uzMaxBodySize, uzMaxChunkSize, uzMaxNumberOfChunks, uzMaximumNumberOfChunksBeforeDisconnecting, uzContentLengthHeaderValue);
        if not bDisconnected:
          # More "headers" may follow.
          ozAdditionalHeaders = oSelf.__foReadAndParseHeaders(cHTTPMessage, uzMaxHeaderNameSize, uzMaxHeaderValueSize, uzMaxNumberOfHeaders);
          for sIllegalName in ["Transfer-Encoding", "Content-Length"]:
            ozIllegalHeader = ozAdditionalHeaders.fozGetUniqueHeaderForName(sIllegalName);
            if ozIllegalHeader is not None:
              raise cHTTPInvalidMessageException(
                "The message was not valid because it contained a %s header after the chunked body." % sIllegalName,
                ozIllegalHeader.fsSerialize(),
              );
      elif uzContentLengthHeaderValue is not None:
        fShowDebugOutput("Reading %d bytes response body..." % uzContentLengthHeaderValue);
        szBody = oSelf.fsReadBytes(uzContentLengthHeaderValue);
      elif bConnectionCloseHeaderPresent:
        fShowDebugOutput("Reading response body until disconnected...");
        szBody = oSelf.fsReadBytesUntilDisconnected(uzMaxNumberOfBytes = uzMaxBodySize);
      else:
        fShowDebugOutput("No response body expected.");
      oMessage = cHTTPMessage(
        ozHeaders = oHeaders,
        szBody = szBody,
        azsBodyChunks = azsBodyChunks,
        ozAdditionalHeaders = ozAdditionalHeaders,
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
  def __fdxReadAndParseStatusLine(oSelf, cHTTPMessage, uzMaxStatusLineSize):
    fShowDebugOutput("Reading status line...");
    szStatusLineCRLF = oSelf.fszReadUntilMarker("\r\n", uzMaxNumberOfBytes = uzMaxStatusLineSize);
    if szStatusLineCRLF is None:
      sStatusLine = oSelf.fsReadBufferedData();
      raise cHTTPInvalidMessageException(
        "The status line was too large.",
        {"sStatusLine": sStatusLine, "uMaxStatusLineSize": uzMaxStatusLineSize},
      );
    fShowDebugOutput("Parsing status line...");
    return cHTTPMessage.fdxParseStatusLine(szStatusLineCRLF[:-2]);
  
  @ShowDebugOutput
  def __foReadAndParseHeaders(oSelf, cHTTPMessage, uzMaxHeaderNameSize, uzMaxHeaderValueSize, uzMaxNumberOfHeaders):
    fShowDebugOutput("Reading headers...");
    uzMaxHeaderLineSize = uzMaxHeaderNameSize + 2 + uzMaxHeaderValueSize if uzMaxHeaderNameSize is not None and uzMaxHeaderValueSize is not None else None;
    asHeaderLines = [];
    while 1:
      szHeaderLineCRLF = oSelf.fszReadUntilMarker("\r\n", uzMaxNumberOfBytes = uzMaxHeaderLineSize);
      if szHeaderLineCRLF is None:
        sHeaderLine = oSelf.fsReadBufferedData();
        raise cHTTPInvalidMessageException(
          "A hreader line was too large.",
          {"sHeaderLine": sHeaderLine, "uMaxHeaderLineSize": uzMaxHeaderLineSize},
        );
      sHeaderLine = szHeaderLineCRLF[:-2];
      if len(sHeaderLine) == 0:
        break; # Empty line == end of headers
      asHeaderLines.append(sHeaderLine);
    return cHTTPMessage.foParseHeaderLines(asHeaderLines);
  
  @ShowDebugOutput
  def __fxReadAndParseBodyChunks(oSelf, cHTTPMessage, uzMaxBodySize, uzMaxChunkSize, uzMaxNumberOfChunks, uzMaximumNumberOfChunksBeforeDisconnecting, uzContentLengthHeaderValue):
    if uzContentLengthHeaderValue is not None:
      fShowDebugOutput("Reading chunked response body WITH Content-Length = %d..." % uzContentLengthHeaderValue);
    else:
      fShowDebugOutput("Reading chunked response body...");
    asBodyChunks = [];
    uTotalNumberOfBodyChunkBytes = 0;
    uTotalNumberOfBodyBytesInChunks = 0;
    while 1:
      if uzMaximumNumberOfChunksBeforeDisconnecting is not None and len(asBodyChunks) == uzMaximumNumberOfChunksBeforeDisconnecting:
        oSelf.fDisconnect();
        return (asBodyChunks, True);
      if uzMaxNumberOfChunks is not None and len(asBodyChunks) == uzMaxNumberOfChunks:
        raise cHTTPInvalidMessageException(
          "There are too many body chunks.",
          {"uMaxNumberOfChunks": uzMaxNumberOfChunks},
        );
      fShowDebugOutput("Reading response body chunk #%d header line..." % (len(asBodyChunks) + 1));
      # Read size in the chunk header
      uzMaxChunkHeaderLineSize = oSelf.uzMaxChunkSizeCharacters + 2 if oSelf.uzMaxChunkSizeCharacters is not None else None;
      if uzContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + 5; # minimum is "0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uzContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            {"uContentLengthHeaderValue": uzContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
        if (
          uzMaxNumberOfBytesInBodyRemaining is not None
          and uzMaxChunkHeaderLineSize is not None
          and uzMaxNumberOfBytesInBodyRemaining < uzMaxChunkHeaderLineSize
        ):
          uzMaxChunkHeaderLineSize = uzMaxNumberOfBytesInBodyRemaining;
      szChunkHeaderLineCRLF = oSelf.fszReadUntilMarker("\r\n", uzMaxNumberOfBytes = uzMaxChunkHeaderLineSize);
      if szChunkHeaderLineCRLF is None:
        sChunkHeaderLine = oSelf.fsReadBufferedData();
        raise cHTTPInvalidMessageException(
          "A body chunk header line was too large.",
          {"sChunkHeaderLine": sChunkHeaderLine, "uMaxChunkHeaderLineSize": uzMaxChunkHeaderLineSize},
        );
      uTotalNumberOfBodyChunkBytes += len(szChunkHeaderLineCRLF);
      sChunkHeaderLine = szChunkHeaderLineCRLF[:-2];
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
      if uzContentLengthHeaderValue is not None:
        uMinimumNumberOfBodyChunksBytes = uTotalNumberOfBodyChunkBytes + uChunkSize + 2 + 7; # minimum after this chunk is "\r\n"+"0\r\n\r\n"
        if uMinimumNumberOfBodyChunksBytes > uzContentLengthHeaderValue:
          raise cHTTPInvalidMessageException(
            "There are more bytes in the body chunks than the Content-Length header indicated.",
            {"uContentLengthHeaderValue": uzContentLengthHeaderValue, "uMinimumNumberOfBodyChunksBytes": uMinimumNumberOfBodyChunksBytes},
          );
      if uzMaxChunkSize is not None and uChunkSize > uzMaxChunkSize:
        raise cHTTPInvalidMessageException(
          "A body chunk was too large.",
          {"uMaxChunkSize": uzMaxChunkSize, "uChunkSize": uChunkSize},
        );
      # Check chunk size and number of chunks
      uTotalNumberOfBodyBytesInChunks += uChunkSize;
      if uzMaxBodySize is not None and uTotalNumberOfBodyBytesInChunks > uzMaxBodySize:
        raise cHTTPInvalidMessageException(
          "There are too many bytes in the body chunks.",
          {"uMaxBodySize": uzMaxBodySize, "uMinimumNumberOfBodyBytesInBodyChunks": uTotalNumberOfBodyBytesInChunks},
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
    if uzContentLengthHeaderValue is not None:
      if uTotalNumberOfBodyChunkBytes < uzContentLengthHeaderValue:
        raise cHTTPInvalidMessageException(
          "There are less bytes in the body chunks than the Content-Length header indicated.",
          {"uContentLengthHeaderValue": uzContentLengthHeaderValue, "uTotalNumberOfBodyChunkBytes": uTotalNumberOfBodyChunkBytes},
        );
    return (asBodyChunks, False);

  @ShowDebugOutput
  def fozSendRequestAndReceiveResponse(oSelf,
    # Send request arguments:
    oRequest, bStartTransaction = True,
    # Receive response arguments:
    uzMaxStatusLineSize = None,
    uzMaxHeaderNameSize = None, uzMaxHeaderValueSize = None, uzMaxNumberOfHeaders = None,
    uzMaxBodySize = None, uzMaxChunkSize = None, uzMaxNumberOfChunks = None,
    uzMaximumNumberOfChunksBeforeDisconnecting = None,
    bEndTransaction = True,
  ):
    if not oSelf.fbSendRequest(oRequest, bStartTransaction = bStartTransaction):
      if not bStartTransaction and bEndTransaction:
        # If we were asked not to start a transaction but we were tasked to
        # end it we should do so:
        oSelf.fEndTransaction();
      return None;
    return oSelf.foReceiveResponse(
      uzMaxStatusLineSize = uzMaxStatusLineSize,
      uzMaxHeaderNameSize = uzMaxHeaderNameSize,
      uzMaxHeaderValueSize = uzMaxHeaderValueSize,
      uzMaxNumberOfHeaders = uzMaxNumberOfHeaders,
      uzMaxBodySize = uzMaxBodySize,
      uzMaxChunkSize = uzMaxChunkSize,
      uzMaxNumberOfChunks = uzMaxNumberOfChunks,
      uzMaximumNumberOfChunksBeforeDisconnecting = uzMaximumNumberOfChunksBeforeDisconnecting,
      bEndTransaction = bEndTransaction,
    );
  
