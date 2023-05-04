SHELL := /usr/bin/env bash
.SHELLFLAGS := -O extglob -c
JENA_HOST := https://dlcdn.apache.org/jena/binaries
JENA_VERSION := 4.8.0

.PHONY: all clean start stop

all: fuseki-server

clean: stop
	rm -rf !(Makefile)

start: fuseki-server
	if [ ! -e run/fuseki.pid ]; then \
	mkdir -p run; \
	./fuseki-server --quiet --file=../../data/dataset.nt /ncg \
	2> run/fuseki.log \
	& echo $$! \
	> run/fuseki.pid; \
	sleep 10; \
	fi

stop:
	if [ -e run/fuseki.pid ]; then \
	kill $$(cat run/fuseki.pid) || true; \
	rm -f run/fuseki.pid; \
	fi

fuseki-server:
	curl $(JENA_HOST)/apache-jena-fuseki-$(JENA_VERSION).tar.gz \
	| tar zxvf - --strip-components 1
