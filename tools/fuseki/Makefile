SHELL := /usr/bin/env bash
.SHELLFLAGS := -O extglob -c
JENA_HOST := https://dlcdn.apache.org/jena/binaries
JENA_VERSION := 4.3.2

.PHONY: all clean start stop

all: fuseki-server

clean: stop
	rm -rf !(Makefile)

start: fuseki-server
	mkdir -p run
	./fuseki-server --file=../../data/dataset.ttl /ncg \
	& echo $$! > run/fuseki.pid

stop:
	if [ -e run/fuseki.pid ]; then \
	kill $$(cat run/fuseki.pid) || true; \
	rm -f run/fuseki.pid; \
	fi

fuseki-server:
	curl $(JENA_HOST)/apache-jena-fuseki-$(JENA_VERSION).tar.gz \
	| tar xvf - --strip-components 1