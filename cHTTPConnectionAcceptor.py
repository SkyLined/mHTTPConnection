from mTCPIPConnections import cTransactionalBufferedTCPIPConnectionAcceptor;

from .cHTTPConnection import cHTTPConnection;

class cHTTPConnectionAcceptor(cTransactionalBufferedTCPIPConnectionAcceptor):
  def foCreateNewConnectionForPythonSocket(oSelf, oPythonSocket):
    return cHTTPConnection(oPythonSocket, bCreatedLocally = False);
