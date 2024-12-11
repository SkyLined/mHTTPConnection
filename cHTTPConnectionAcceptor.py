from mTCPIPConnection import cTransactionalBufferedTCPIPConnectionAcceptor;

from .cHTTPConnection import cHTTPConnection;

class cHTTPConnectionAcceptor(cTransactionalBufferedTCPIPConnectionAcceptor):
  u0DefaultNonSSLPortNumber = 80;
  u0DefaultSSLPortNumber = 443;
  def foCreateNewConnectionForPythonSocket(oSelf, oPythonSocket):
    return cHTTPConnection(oPythonSocket, bCreatedLocally = False);
