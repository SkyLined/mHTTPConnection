Implementation of HTTP protocol over TCP/IP sockets, based on mTCPIPConnections
and mHTTPProtocol.

`cHTTPConnection`
-----------------
Implements a single connection between a HTTP server and a HTTP client; can be
used by both the client and the server. Implements
`cTransactionalBufferedTCPIPConnection`.

`cHTTPConnectionAcceptor`
-------------------------
Implements a server socket for a HTTP server; can be used by a server to accept
connections as `cHTTPConnections`. Implements
`cTransactionalBufferedTCPIPConnectionAcceptor`.
