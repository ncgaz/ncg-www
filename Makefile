PYTHON := ./venv/bin/python

GDB_HOST := https://prd-tnm.s3.amazonaws.com/StagedProducts

upper = $(shell echo $(1) | tr '[:lower:]' '[:upper:]')

.PHONY: all clean

.PRECIOUS: %_North_Carolina_State_GDB.zip

all: map.png

clean:
	rm -rf venv map.png

$(PYTHON): requirements.txt
	python3 -m venv venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install wheel
	$(PYTHON) -m pip install -r $<

%_North_Carolina_State_GDB.zip:
	curl $(GDB_HOST)/$*/GDB/$(call upper,$*)_North_Carolina_State_GDB.zip \
	> $@

map.png: $(PYTHON)
	$(PYTHON) map.py
