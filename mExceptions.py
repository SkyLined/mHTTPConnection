# Passdown from mHTTPProtocol and mTCPIPConnection, which in turn passes down from mSSL if available
from mHTTPProtocol.mExceptions import *;
from mHTTPProtocol.mExceptions import acExceptions as acHTTPProtocolExceptions;
from mTCPIPConnection.mExceptions import *;
from mTCPIPConnection.mExceptions import acExceptions as acTCPIPConnectionExceptions;

try: # mSSL support is optional
  from mSSL.mExceptions import *;
  from mSSL.mExceptions import acExceptions as acSSLExceptions;
except ModuleNotFoundError as oException:
  if oException.args[0] != "No module named 'mSSL'":
    raise;
  acSSLExceptions = [];

acExceptions = (
  acTCPIPConnectionExceptions + 
  acSSLExceptions +
  acHTTPProtocolExceptions
);
