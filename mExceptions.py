# Passdown from mHTTPProtocol and mTCPIPConnections, which in turn passes down from mSSL if available
from mHTTPProtocol.mExceptions import *;
from mTCPIPConnections.mExceptions import *;

class cMaxConnectionsReachedException(cHTTPException):
  pass; # The client would need to create more connections to the server than allowed.

class cHTTPOutOfBandDataException(cHTTPException):
  pass; # The remote send data when it was not expected to do so (i.e. the server send data before a request was made).
