# ICHARG and fixed-charge calculation context
Source: https://vasp.at/wiki/index.php/ICHARG
Keywords: ICHARG, fixed charge, non-self-consistent settings
Reviewed: 2026-10-30

Official-source summary: ICHARG controls how the initial charge density is constructed. For ICHARG values greater than or equal to 10, the charge density remains fixed during electronic minimization; related settings should be interpreted in the context of non-self-consistent calculations.

Project policy: An ICHARG value observed in the prefix does not prove that it belongs to the same run as the final sampled loop, that the setting is valid, or that the calculation succeeded. A fixed-charge note only prompts a check of the applicable calculation mode; it does not invalidate an observed EDIFF not-reached message or establish that the message is normal. Missing or ambiguous observations do not imply a default value. The project does not modify ICHARG automatically.
