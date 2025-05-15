# Times Square

**Times Square is a Rubin Science Platform (RSP) service for displaying parameterized Jupyter Notebooks as websites.**

Excellent applications for Times Square include:

- Engineering dashboards
- Quick-look data previewing
- Reports that incorporate live data sources

## Deployments of Times Square

| Link                                                                  | User guide                                                                     | Purpose                     |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------- |
| [USDF RSP](https://usdf-rsp.slac.stanford.edu/times-square)           | [Documentation](https://rsp.lsst.io/v/usdfprod/guides/times-square/index.html) | For Rubin Observatory staff |
| [data.lsst.cloud](https://data.lsst.cloud/times-square)               | [Documentation](https://rsp.lsst.io/v/idfdev/guides/times-square/index.html)   | Internal metrics reporting  |
| [USDF RSP (dev)](https://usdf-rsp-dev.slac.stanford.edu/times-square) | [Documentation](https://rsp.lsst.io/v/usdfdev/guides/times-square/index.html)  | Feature testing             |
| [IDF (dev)](https://data-dev.lsst.cloud/times-square)                 | [Documentation](https://rsp.lsst.io/v/idfdev/guides/times-square/index.html)   | For SQuaRE developers       |

## Design and development

The design and architecture of Times Square is described in [SQR-062: The Times Square service for publishing parameterized Jupyter Notebooks in the Rubin Science platform](https://sqr-062.lsst.io).
Times Square uses [Noteburst](https://noteburst.lsst.io) ([GitHub](https://github.com/lsst-sqre/noteburst), [SQR-065](https://sqr-065.lsst.io)) to execute Jupyter Notebooks in Nublado (JupyterLab) instances, thereby mechanizing the RSP's notebook aspect.

This Times Square API service is developed at https://github.com/lsst-sqre/times-square.
Its user interface is part of [Squareone](https://github.com/lsst-sqre/squareone).
Times Square is deployed with [Phalanx](https://phalanx.lsst.io/applications/times-square/index.html).

REST API and developer documentation is at [times-square.lsst.io](https://times-square.lsst.io) and deployment documentation is [available at phalanx.lsst.io](https://phalanx.lsst.io/applications/times-square/index.html).
