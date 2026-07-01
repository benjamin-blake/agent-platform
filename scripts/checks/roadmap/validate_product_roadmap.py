"""Product roadmap schema validation (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_product_roadmap", owner="platform", product_coupled=True)
def validate_product_roadmap(failed: list[str]) -> None:
    """Validate docs/ROADMAP-PRODUCT.yaml against the ProductRoadmapDocument Pydantic schema.

    Includes cross-roadmap resolution against PLATFORM. Runs in BOTH --pre and full
    presubmit (diverges from validate_platform_roadmap which is full-tier only; the product
    check is pure Python over a single YAML file and runs in well under 100ms -- ROADMAP-
    PRODUCT.yaml is the active editing surface and catching structural drift in the fast-tier
    loop is high-value for product editors without denting the fast-tier budget).
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Product roadmap schema validation ===")

    product_path = _common.ROOT / "docs" / "ROADMAP-PRODUCT.yaml"
    platform_path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not product_path.exists():
        print(f"  FAIL: {product_path.relative_to(_common.ROOT)} not found")
        failed.append("Product roadmap schema validation")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from pydantic import ValidationError  # noqa: PLC0415

        from scripts.product_roadmap import load  # noqa: PLC0415

        load(product_path, platform_path=platform_path)
        print("  PASS: product roadmap schema validation passed.")
    except ImportError as exc:
        print(f"  ERROR: Could not import product_roadmap: {exc}")
        failed.append("Product roadmap schema validation")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Product roadmap schema validation")
    except ValidationError as exc:
        print(f"  FAIL: Pydantic validation error:\n{exc}")
        failed.append("Product roadmap schema validation")
    except (ValueError, OSError) as exc:
        print(f"  FAIL: {exc}")
        failed.append("Product roadmap schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
