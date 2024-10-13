# Times Square

**Times Square is a Rubin Science Platform (RSP) service for displaying parameterized Jupyter Notebooks as websites.**

Excellent applications for Times Square include:

- Engineering dashboards
- Quick-look data previewing
- Reports that incorporate live data sources

The design and architecture of Times Square is described in [SQR-062: The Times Square service for publishing parameterized Jupyter Notebooks in the Rubin Science platform](https://sqr-062.lsst.io).
Times Square uses [Noteburst](https://noteburst.lsst.io) ([GitHub](https://github.com/lsst-sqre/noteburst), [SQR-065](https://sqr-065.lsst.io)) to execute Jupyter Notebooks in Nublado (JupyterLab) instances, thereby mechanizing the RSP's notebook aspect.

This Times Square API service is developed at https://github.com/lsst-sqre/times-square.
It's user interface is part of [Squareone](https://github.com/lsst-sqre/squareone).
Times Square is deployed with [Phalanx](https://phalanx.lsst.io/applications/times-square/index.html).

Documentation on how to set up notebooks for times-square is at https://rsp.lsst.io/v/usdfdev/guides/times-square/authoring/authoring-howto.html ,
