from mTCPIPConnection import cTransactionalBufferedTCPIPConnectionAcceptor;

from .cConnection import cConnection;

class cConnectionAcceptor(cTransactionalBufferedTCPIPConnectionAcceptor):
  u0DefaultNonSSLPortNumber = 80;
  u0DefaultSSLPortNumber = 443;
  def foCreateNewConnectionForPythonSocket(oSelf, oPythonSocket):
    return cConnection(oPythonSocket, bCreatedLocally = False);
