# Passdown from mHTTPProtocol
from mHTTPProtocol.mHTTPExceptions import *;
from mTCPIPConnections.mTCPIPExceptions import *;

class cMaxConnectionsReachedException(cHTTPException):
  pass; # The client would need to create more connections to the server than allowed.

class cOutOfBandDataException(cHTTPException):
  pass; # The remote send data when it was not expected to do so (i.e. the server send data before a request was made).
