GDB_HOST := https://prd-tnm.s3.amazonaws.com/StagedProducts
DATASET := ../ncg-dataset/dataset.nt

space := $(empty) $(empty)
upper = $(shell echo $(1) | tr '[:lower:]' '[:upper:]')
state = $(subst $(space),_,$(wordlist 2,3,$(subst _, ,$1)))
type = $(word 1,$(subst _, ,$1))
gdbpath = $(call type,$*)/GDB/$(call upper,$(call type,$*))_$(call state,$*)

.PHONY: all clean superclean serve tools/maps tools/fuseki tools/snowman dataset.nt

.PRECIOUS: data/%_State_GDB.zip

all: site/index.html

clean:
	rm -rf site .snowman

superclean: clean
	rm -rf data static/maps
	$(MAKE) -s -C tools/maps clean
	$(MAKE) -s -C tools/fuseki clean
	$(MAKE) -s -C tools/snowman clean

serve: site/index.html
	./tools/snowman/snowman server

tools/maps tools/fuseki tools/snowman:
	@$(MAKE) -s -C $@

dataset.nt:
	[ -f $(DATASET) ] && cat $(DATASET) > $@ || true

data/%_State_GDB.zip:
	mkdir -p data
	curl $(GDB_HOST)/$(call gdbpath,$*)_State_GDB.zip \
	> $@

static/maps/.done: \
dataset.nt \
data/GovtUnit_North_Carolina_State_GDB.zip \
data/GovtUnit_South_Carolina_State_GDB.zip \
data/GovtUnit_Georgia_State_GDB.zip \
data/GovtUnit_Tennessee_State_GDB.zip \
data/GovtUnit_Virginia_State_GDB.zip \
| tools/maps
	./tools/maps/venv/bin/python -W error \
	./tools/maps/map.py --geometry-check error static/maps $^
	touch $@

site/index.html: \
$(wildcard *.yaml) \
$(wildcard queries/*.rq) \
$(wildcard templates/*.html) \
$(wildcard templates/layouts/*.html) \
| tools/fuseki tools/snowman
	./tools/fuseki/fuseki-server --file=dataset.ttl /ncg
	# $(MAKE) -s -C tools/fuseki start
	# mkdir -p .snowman
	# ./tools/snowman/snowman build \
	# | tee .snowman/build_log.txt \
	# | grep -vE "^Issuing parameterized query" \
	# | grep -vE "^Rendered page at site/NCG[[:digit:]]+\.html$$"
	# cat tools/fuseki/run/fuseki.log
	# $(MAKE) -s -C tools/fuseki stop
