"""Other Kodex servers (KODEX_PEERS): which of a series' books another
server already has, and copying the missing ones there ("Kopiera vol 5–10
till Hemma-NAS").

Servers talk to each other with the receiving server's upload key
(X-Kodex-Upload-Key, its UPLOAD_API_KEY): the secret its POST
/libraries/{id}/upload takes, and the small read-only /federation API
(``api``) for its libraries and which books it holds. Books match by
content_hash (the same file), else by series title, number and edition
type (the same volume from another release).
"""
