from mTCPIPConnection import cTransactionalBufferedTCPIPConnectionAcceptor;

from .cHTTPConnection import cHTTPConnection;
from .mExceptions import acExceptions;

class cHTTPConnectionAcceptor(cTransactionalBufferedTCPIPConnectionAcceptor):
  u0DefaultNonSSLPortNumber = 80;
  u0DefaultSSLPortNumber = 443;
  def foCreateNewConnectionForPythonSocket(oSelf, oPythonSocket):
    return cHTTPConnection(oPythonSocket, bCreatedLocally = False);

for cException in acExceptions:
  setattr(cHTTPConnectionAcceptor, cException.__name__, cException);
