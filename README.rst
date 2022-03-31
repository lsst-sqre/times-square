############
Times Square
############

**Times Square is a Rubin Science Platform (RSP) service for displaying parameterized Jupyter Notebooks as websites.**

Excellent applications for Times Square include:

- Engineering dashboards
- Quick-look data previewing
- Reports that incorporate live data sources

The design and architecture of Times Square is described in `SQR-062: The Times Square service for publishing parameterized Jupyter Notebooks in the Rubin Science platform <https://sqr-062.lsst.io>`__.
Times Square uses Noteburst (`GitHub <https://github.com/lsst-sqre/noteburst>`__, `SQR-065 <https://sqr-065.lsst.io>`__) to execute Jupyter Notebooks in Nublado (JupyterLab) instances, thereby mechanizing the RSP's notebook aspect.

This Times Square API service is developed at `https://github.com/lsst-sqre/times-square <https://github.com/lsst-sqre/times-square>`__.
The user interface is developed separately at `https://github.com/lsst-sqre/times-square-ui <https://github.com/lsst-sqre/times-square-ui>`__.
You can find the RSP deployment configuration in Phalanx's `services/times-square/ <https://github.com/lsst-sqre/phalanx/tree/master/services/times-square>`__ directory.
