"""Symbol universe definitions.

Provides lists of ticker symbols for different indices and custom watchlists.
FTSE 100 constituents use the .L suffix for the London Stock Exchange.

The FTSE 100 list is hardcoded for reliability — it changes infrequently
(quarterly reviews). A future enhancement could fetch it dynamically.
"""

from typing import List


class SymbolUniverse:
    """Manages ticker symbol lists by index or custom watchlist."""

    # FTSE 100 constituents as of March 2026
    # Source: London Stock Exchange quarterly review
    # Suffix .L = London Stock Exchange on Yahoo Finance
    FTSE_100 = [
        "III.L",  # 3i Group
        "ABF.L",  # Associated British Foods
        "ADM.L",  # Admiral Group
        "AAF.L",  # Airtel Africa
        "AAL.L",  # Anglo American
        "ANTO.L",  # Antofagasta
        "AHT.L",  # Ashtead Group
        "ABG.L",  # Abrdn
        "AZN.L",  # AstraZeneca
        "AUTO.L",  # Auto Trader Group
        "AVV.L",  # AVEVA Group
        "AV.L",  # Aviva
        "BME.L",  # B&M European Value Retail
        "BA.L",  # BAE Systems
        "BARC.L",  # Barclays
        "BDEV.L",  # Barratt Developments
        "BKG.L",  # Berkeley Group
        "BEZ.L",  # Beazley
        "BP.L",  # BP
        "BATS.L",  # British American Tobacco
        "BLND.L",  # British Land
        "BT.A.L",  # BT Group
        "BNZL.L",  # Bunzl
        "BRBY.L",  # Burberry
        "CNA.L",  # Centrica
        "CCH.L",  # Coca-Cola HBC
        "CPG.L",  # Compass Group
        "CRDA.L",  # Croda International
        "DCC.L",  # DCC
        "DGE.L",  # Diageo
        "DPLM.L",  # Diploma
        "EDV.L",  # Endeavour Mining
        "ENT.L",  # Entain
        "EXPN.L",  # Experian
        "FRAS.L",  # Frasers Group
        "GLEN.L",  # Glencore
        "GSK.L",  # GSK
        "HLN.L",  # Haleon
        "HL.L",  # Hargreaves Lansdown
        "HSBA.L",  # HSBC Holdings
        "IMB.L",  # Imperial Brands
        "INF.L",  # Informa
        "IHG.L",  # InterContinental Hotels
        "IAG.L",  # International Airlines Group
        "ITRK.L",  # Intertek Group
        "JD.L",  # JD Sports
        "KGF.L",  # Kingfisher
        "LAND.L",  # Land Securities
        "LGEN.L",  # Legal & General
        "LLOY.L",  # Lloyds Banking Group
        "LSEG.L",  # London Stock Exchange Group
        "MNG.L",  # M&G
        "MKS.L",  # Marks & Spencer
        "MRO.L",  # Melrose Industries
        "MNDI.L",  # Mondi
        "NG.L",  # National Grid
        "NWG.L",  # NatWest Group
        "NXT.L",  # Next
        "OCDO.L",  # Ocado Group
        "PSON.L",  # Pearson
        "PSH.L",  # Pershing Square Holdings
        "PSN.L",  # Persimmon
        "PHOENIX.L",  # Phoenix Group
        "PHNX.L",  # Phoenix Group (alt)
        "PRU.L",  # Prudential
        "RKT.L",  # Reckitt Benckiser
        "REL.L",  # RELX
        "RTO.L",  # Rentokil Initial
        "RIO.L",  # Rio Tinto
        "RR.L",  # Rolls-Royce Holdings
        "RS1.L",  # RS Group
        "SGE.L",  # Sage Group
        "SBRY.L",  # Sainsbury's
        "SDR.L",  # Schroders
        "SMT.L",  # Scottish Mortgage Invest. Trust
        "SGRO.L",  # Segro
        "SVT.L",  # Severn Trent
        "SHEL.L",  # Shell
        "SN.L",  # Smith & Nephew
        "SMDS.L",  # Smith (DS)
        "SMIN.L",  # Smiths Group
        "SKG.L",  # Smurfit Kappa
        "SPX.L",  # Spirax-Sarco Engineering
        "SSE.L",  # SSE
        "STJ.L",  # St James's Place
        "STAN.L",  # Standard Chartered
        "TW.L",  # Taylor Wimpey
        "TSCO.L",  # Tesco
        "ULVR.L",  # Unilever
        "UTG.L",  # Unite Group
        "UU.L",  # United Utilities
        "VOD.L",  # Vodafone Group
        "WEIR.L",  # Weir Group
        "WTB.L",  # Whitbread
        "WPP.L",  # WPP
    ]

    @classmethod
    def get_ftse_100(cls) -> List[str]:
        """Return FTSE 100 constituents.

        Returns:
            List of LSE ticker symbols with .L suffix.
        """
        return list(cls.FTSE_100)

    @classmethod
    def get_custom(cls, tickers: List[str]) -> List[str]:
        """Return a custom watchlist.

        Args:
            tickers: User-specified ticker symbols.

        Returns:
            The input list (validated for non-empty strings).
        """
        return [t.strip() for t in tickers if t.strip()]

    @classmethod
    def get_universe(cls, name: str, custom_tickers: List[str] = None) -> List[str]:
        """Resolve a universe name to a list of symbols.

        Args:
            name: Universe identifier ('ftse_100', 'custom').
            custom_tickers: Required when name='custom'.

        Returns:
            List of ticker symbols.

        Raises:
            ValueError: If name is unrecognised or custom_tickers missing.
        """
        if name == "ftse_100":
            return cls.get_ftse_100()
        elif name == "custom":
            if not custom_tickers:
                raise ValueError("custom_tickers must be provided when universe='custom'")
            return cls.get_custom(custom_tickers)
        else:
            raise ValueError(f"Unknown universe '{name}'. Supported: ftse_100, custom")
