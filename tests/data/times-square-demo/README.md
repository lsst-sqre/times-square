# times-square-demo datasets

This directory contains sample data based on `lsst-sqre/times-square-demo`.

## recursive_tree.json

```sh
http get "https://api.github.com/repos/lsst-sqre/times-square-demo/git/trees/aa0e977e257bd7d9d9d3f520b18b22bd3d9c6e49?recursive=1" "Accept:application/vnd.github.v3+json" --download -o tests/data/times-square-demo/recursive_tree.json
```
