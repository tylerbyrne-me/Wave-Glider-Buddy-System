"""Registry for checklist-only PIC handoff sensors."""

PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY: dict[str, str] = {
    "adcp": "ADCP",
}


def get_pic_handoff_optional_sensor_keys() -> set[str]:
    """Return allowed checklist-only sensor keys."""
    return set(PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY.keys())
