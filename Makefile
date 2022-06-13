GDB_HOST := https://prd-tnm.s3.amazonaws.com/StagedProducts

upper = $(shell echo $(1) | tr '[:lower:]' '[:upper:]')

.PHONY: all clean superclean serve tools/maps tools/fuseki tools/snowman

.PRECIOUS: data/%_North_Carolina_State_GDB.zip

all: site/index.html

clean:
	rm -rf site
	$(MAKE) -s -C tools/maps clean
	$(MAKE) -s -C tools/fuseki clean
	$(MAKE) -s -C tools/snowman clean

superclean: clean
	rm -rf data site static/maps

serve: site/index.html
	./tools/snowman/snowman server

tools/maps tools/fuseki tools/snowman:
	$(MAKE) -s -C $@

data/dataset.ttl:
	mkdir -p data
	cat ../ncg-dataset/dataset.ttl \
	> $@

data/%_North_Carolina_State_GDB.zip:
	mkdir -p data
	curl $(GDB_HOST)/$*/GDB/$(call upper,$*)_North_Carolina_State_GDB.zip \
	> $@

static/maps/.done: \
data/dataset.ttl \
data/GovtUnit_North_Carolina_State_GDB.zip \
| tools/maps
	./tools/maps/venv/bin/python -W error ./tools/maps/map.py $^ static/maps
	touch $@

site/index.html: \
static/maps/.done \
$(wildcard *.yaml) \
$(wildcard queries/*.rq) \
$(wildcard templates/*.html) \
$(wildcard templates/layouts/*.html) \
| tools/fuseki tools/snowman
	$(MAKE) -s -C tools/fuseki start
	mkdir -p .snowman
	./tools/snowman/snowman build \
	| tee .snowman/build_log.txt \
	| grep -vE "^Issuing parameterized query" \
	| grep -vE "^Rendered page at site/NCG[[:digit:]]+\.html$$"
	$(MAKE) -s -C tools/fuseki stop
