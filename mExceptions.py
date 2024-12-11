class cHTTPConnectionException(Exception):
  def __init__(oSelf, sMessage, *, o0Connection = None, dxDetails = None):
    assert isinstance(dxDetails, dict), \
        "dxDetails must be a dict, not %s" % repr(dxDetails);
    oSelf.sMessage = sMessage;
    oSelf.o0Connection = o0Connection;
    oSelf.dxDetails = dxDetails;
    Exception.__init__(oSelf, sMessage, o0Connection, dxDetails);
  
  def fasDetails(oSelf):
    return (
      (["Remote: %s" % str(oSelf.o0Connection.sbRemoteAddress, "ascii", "strict")] if oSelf.o0Connection else [])
      + ["%s: %s" % (str(sName), repr(xValue)) for (sName, xValue) in oSelf.dxDetails.items()]
    );
  def __str__(oSelf):
    return "%s (%s)" % (oSelf.sMessage, ", ".join(oSelf.fasDetails()));
  def __repr__(oSelf):
    return "<%s.%s %s>" % (oSelf.__class__.__module__, oSelf.__class__.__name__, oSelf);

class cHTTPMaximumNumberOfConnectionsToServerReachedException(cHTTPConnectionException):
  pass;

class cHTTPConnectionOutOfBandDataException(cHTTPConnectionException):
  pass;

__all__ = [
  "cHTTPConnectionException",
  "cHTTPConnectionOutOfBandDataException",
  "cHTTPMaximumNumberOfConnectionsToServerReachedException",
];
