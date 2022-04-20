# rsp_broadcast datasets

This directory contains sample datasets related to the `lsst-sqre/rsp_broadcast` GitHub repository.
The purpose of this data is capture GitHub API responses related to a relatively simple Git repository.
In the future this data could be related with that of a demo Times Square notebook repository.

## recursive_tree.json

```sh
http get "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/trees/46372dfa5a432026d68d262899755ef0333ef8c0?recursive=1" "Accept:application/vnd.github.v3+json" --download -o tests/data/rsp_broadcast/recursive_tree.json
```
## readme_blob.json

```sh
http get "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/blobs/8e977bc4a1503adb11e3fe06e0ddcf759ad59a91" "Accept:application/vnd.github.v3+json" --download -o tests/data/rsp_broadcast/readme_blob.json
```
