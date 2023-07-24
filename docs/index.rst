:html_theme.sidebar_secondary.remove:

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
It's user interface is part of `Squareone <https://github.com/lsst-sqre/squareone>`__.
Times Square is deployed with `Phalanx <https://phalanx.lsst.io/applications/times-square/index.html>`__.

.. toctree::
   :hidden:

   user-guide/index
   api
   changelog
   Development <dev/index>
