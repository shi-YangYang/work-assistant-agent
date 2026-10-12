encode zstd gzip
request_body {
	max_size 35MB
}
header {
	X-Content-Type-Options nosniff
	Referrer-Policy same-origin
	Permissions-Policy "camera=(), microphone=(self)"
	Content-Security-Policy "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
}
handle /api/* {
	reverse_proxy api:8000 {
		# This is the public edge: replace client-supplied forwarding headers.
		header_up X-Forwarded-For {http.request.remote.host}
		header_up X-Forwarded-Proto {http.request.scheme}
		flush_interval -1
	}
}
handle {
	root * /srv
	try_files {path} /index.html
	file_server
}
