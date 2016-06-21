.PHONY: js/index.js

.SUFFIXES: .elm .elmx .js

all: js/index.js

%.elm: %.elmx
	node elmx.js $^ > $@

js/index.js: src/Main.elm
	elm make --output $@ $^
