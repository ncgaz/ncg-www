PYTHON := ./venv/bin/python

.PHONY: all clean

all: $(PYTHON)

clean:
	rm -rf venv

$(PYTHON): requirements.txt
	python3 -m venv venv
	$@ -m pip install --upgrade pip
	$@ -m pip install wheel
	$@ -m pip install -r $<
	touch $@
