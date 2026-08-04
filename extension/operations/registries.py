"""Shared allowlists and compatibility hints for controlled operations."""

MATERIAL_FAMILIES = (
    "matte_plastic",
    "glossy_plastic",
    "metal",
    "brushed_metal",
    "painted_metal",
    "rubber",
    "ceramic",
    "glass",
    "wood",
    "stone",
    "fabric",
    "emission",
    "emissive",
)

PROCEDURAL_PATTERNS = (
    "noise",
    "wood_grain",
    "checker",
    "checkerboard",
    "marble",
    "stone_noise",
    "fabric_weave",
    "brushed_metal",
    "paint_speckle",
)

SHADER_LAYER_TYPES = (
    "base",
    "paint",
    "dust",
    "edge_wear",
    "scratches",
    "clearcoat",
    "emission_detail",
    "decal",
)

SHADER_LAYER_BLEND_MODES = (
    "mix",
    "multiply",
    "add",
    "screen",
    "overlay",
)

SHADER_LAYER_MASK_KINDS = (
    "procedural",
    "image",
    "uv_map",
    "vertex_group",
)

ADVANCED_PROCEDURAL_PATTERNS = (
    "marble",
    "granite",
    "brushed_metal",
    "oxidation",
    "peeling_paint",
    "ceramic_crackle",
    "carbon_fiber",
    "fabric_weave",
    "skin_pores",
    "water_ripples",
)

PROCEDURAL_NODE_SET_MAPPINGS = (
    "generated",
    "object",
    "uv",
)

SHADING_REFERENCE_TEMPLATE_FAMILIES = (
    "matte_plastic",
    "glossy_plastic",
    "metal",
    "brushed_metal",
    "painted_metal",
    "rubber",
    "ceramic",
    "glass",
    "wood",
    "stone",
    "fabric",
    "emission",
)

SHADING_REPAIR_MODES = (
    "validate_only",
    "single_safe_fix",
)

SHADER_LAYOUT_STYLES = (
    "compact",
    "readable",
)

SHADER_PREVIEW_MODES = (
    "material",
    "split",
)

SHADER_NODE_TYPES = (
    "ShaderNodeTexNoise",
    "ShaderNodeTexVoronoi",
    "ShaderNodeTexWave",
    "ShaderNodeTexChecker",
    "ShaderNodeTexImage",
    "ShaderNodeBump",
    "ShaderNodeNormalMap",
    "ShaderNodeValToRGB",
    "ShaderNodeMapping",
    "ShaderNodeTexCoord",
    "ShaderNodeMath",
    "ShaderNodeMix",
    "ShaderNodeEmission",
)

SHADER_NODE_REFERENCES = ("principled_bsdf", "material_output")

SHADER_SOCKET_NAMES = (
    "BSDF",
    "Base Color",
    "Metallic",
    "Roughness",
    "Alpha",
    "Normal",
    "Emission Color",
    "Emission Strength",
    "Emission",
    "Surface",
    "Vector",
    "Fac",
    "Color",
    "Value",
    "Scale",
    "Detail",
    "Distortion",
    "Distance",
    "Height",
    "Strength",
    "Generated",
    "Object",
    "UV",
)

SHADER_SOCKET_FAMILIES = {
    "BSDF": "shader",
    "Base Color": "color",
    "Metallic": "float",
    "Roughness": "float",
    "Alpha": "float",
    "Normal": "normal",
    "Emission Color": "color",
    "Emission Strength": "float",
    "Emission": "shader",
    "Surface": "shader",
    "Vector": "vector",
    "Fac": "float",
    "Color": "color",
    "Value": "float",
    "Scale": "float",
    "Detail": "float",
    "Distortion": "float",
    "Distance": "float",
    "Height": "float",
    "Strength": "float",
    "Generated": "vector",
    "Object": "vector",
    "UV": "vector",
}

SHADER_SOCKET_COMPATIBILITY = {
    "float": ("float", "color"),
    "color": ("color", "float"),
    "vector": ("vector", "normal", "color"),
    "normal": ("normal", "vector"),
    "shader": ("shader",),
}

SHADER_NODE_COMPATIBILITY = {
    "ShaderNodeTexNoise": {
        "category": "texture",
        "inputs": {
            "Vector": "vector",
            "Scale": "float",
            "Detail": "float",
            "Roughness": "float",
            "Distortion": "float",
        },
        "outputs": {"Fac": "float", "Color": "color"},
        "safe_defaults": {"Scale": 5.0, "Detail": 8.0, "Roughness": 0.5},
    },
    "ShaderNodeTexVoronoi": {
        "category": "texture",
        "inputs": {"Vector": "vector", "Scale": "float"},
        "outputs": {"Distance": "float", "Color": "color"},
        "safe_defaults": {"Scale": 5.0},
    },
    "ShaderNodeTexWave": {
        "category": "texture",
        "inputs": {"Vector": "vector", "Scale": "float", "Distortion": "float"},
        "outputs": {"Color": "color", "Fac": "float"},
        "safe_defaults": {"Scale": 8.0, "Distortion": 5.0},
    },
    "ShaderNodeTexChecker": {
        "category": "texture",
        "inputs": {"Vector": "vector", "Scale": "float"},
        "outputs": {"Color": "color", "Fac": "float"},
        "safe_defaults": {"Scale": 8.0},
    },
    "ShaderNodeTexImage": {
        "category": "texture",
        "inputs": {"Vector": "vector"},
        "outputs": {"Color": "color", "Alpha": "float"},
        "safe_defaults": {},
    },
    "ShaderNodeBump": {
        "category": "normal",
        "inputs": {"Height": "float", "Strength": "float", "Normal": "normal"},
        "outputs": {"Normal": "normal"},
        "safe_defaults": {"Strength": 0.1},
    },
    "ShaderNodeNormalMap": {
        "category": "normal",
        "inputs": {"Color": "color", "Strength": "float"},
        "outputs": {"Normal": "normal"},
        "safe_defaults": {"Strength": 1.0},
    },
    "ShaderNodeValToRGB": {
        "category": "converter",
        "inputs": {"Fac": "float"},
        "outputs": {"Color": "color", "Alpha": "float"},
        "safe_defaults": {},
    },
    "ShaderNodeMapping": {
        "category": "vector",
        "inputs": {"Vector": "vector", "Scale": "vector"},
        "outputs": {"Vector": "vector"},
        "safe_defaults": {"Scale": (1.0, 1.0, 1.0)},
    },
    "ShaderNodeTexCoord": {
        "category": "input",
        "inputs": {},
        "outputs": {"Generated": "vector", "Object": "vector", "UV": "vector"},
        "safe_defaults": {},
    },
    "ShaderNodeMath": {
        "category": "converter",
        "inputs": {"Value": "float"},
        "outputs": {"Value": "float"},
        "safe_defaults": {},
    },
    "ShaderNodeMix": {
        "category": "converter",
        "inputs": {"Fac": "float", "Color": "color", "Value": "float"},
        "outputs": {"Color": "color", "Value": "float"},
        "safe_defaults": {"Fac": 0.5},
    },
    "ShaderNodeEmission": {
        "category": "shader",
        "inputs": {"Color": "color", "Strength": "float"},
        "outputs": {"Emission": "shader"},
        "safe_defaults": {"Strength": 1.0},
    },
    "principled_bsdf": {
        "category": "builtin",
        "inputs": {
            "Base Color": "color",
            "Metallic": "float",
            "Roughness": "float",
            "Alpha": "float",
            "Normal": "normal",
            "Emission Color": "color",
            "Emission Strength": "float",
        },
        "outputs": {"BSDF": "shader"},
        "safe_defaults": {},
    },
    "material_output": {
        "category": "builtin",
        "inputs": {"Surface": "shader"},
        "outputs": {},
        "safe_defaults": {},
    },
}

SHADER_MIX_CHAIN_TEMPLATES = (
    "noise_to_base_color",
    "noise_bump",
    "emission_overlay",
)

SHADER_GRAPH_TEMPLATES = (
    "layered_noise_material",
    "emission_rim_material",
    "bump_detail_material",
)

PROCEDURAL_SHADER_NODE_TYPES = frozenset(
    {
        "ShaderNodeTexNoise",
        "ShaderNodeTexVoronoi",
        "ShaderNodeTexWave",
        "ShaderNodeTexChecker",
    }
)

IMAGE_TEXTURE_NODE_TYPES = frozenset({"ShaderNodeTexImage"})
BUMP_OR_NORMAL_NODE_TYPES = frozenset({"ShaderNodeBump", "ShaderNodeNormalMap"})

UV_OPERATION_NAMES = (
    "CREATE_IMAGE_TEXTURE_NODE",
    "SET_TEXTURE_MAPPING",
    "CREATE_UV_MAP",
    "ASSIGN_UV_MAP",
    "UNWRAP_UV_MAP",
    "PACK_UV_ISLANDS",
    "INSPECT_UV_MAP",
    "CREATE_UV_DIAGNOSTIC_REPORT",
    "CREATE_UV_OVERLAP_PREVIEW",
    "CREATE_UV_STRETCH_PREVIEW",
    "MARK_UV_SEAMS_BY_ANGLE",
    "MARK_UV_SEAMS_BY_MATERIAL",
    "MARK_UV_SEAMS_BY_EDGE_SET",
    "CLEAR_UV_SEAMS",
    "CREATE_UV_ISLANDS_FROM_SEAMS",
    "SMART_PROJECT_UV_MAP",
    "CUBE_PROJECT_UV_MAP",
    "CYLINDER_PROJECT_UV_MAP",
    "SPHERE_PROJECT_UV_MAP",
    "CAMERA_PROJECT_UV_MAP",
    "LIGHTMAP_UNWRAP_UV_MAP",
    "SELECT_UV_ISLANDS_BY_MATERIAL",
    "TRANSFORM_UV_ISLANDS",
    "ALIGN_UV_ISLANDS",
    "DISTRIBUTE_UV_ISLANDS",
    "SCALE_UV_ISLANDS_TO_BOUNDS",
    "PIN_UV_ISLANDS",
    "UNPIN_UV_ISLANDS",
    "SET_UV_TEXEL_DENSITY",
    "NORMALIZE_UV_TEXEL_DENSITY",
    "PACK_UV_ISLANDS_ADVANCED",
    "MOVE_UV_ISLANDS_TO_TILE",
    "CREATE_UDIM_TILE_LAYOUT",
    "VALIDATE_UDIM_LAYOUT",
    "RELAX_UV_ISLANDS",
    "MINIMIZE_UV_STRETCH",
    "REPAIR_UV_BOUNDS",
    "MERGE_DUPLICATE_UV_MAPS",
    "REMOVE_UNUSED_ASSISTANT_UV_MAPS",
    "VALIDATE_UV_MAP",
    "FIT_UV_ISLANDS_TO_IMAGE_REGION",
    "CREATE_TEXTURE_ATLAS_LAYOUT",
    "ASSIGN_ATLAS_TEXTURE_REGIONS",
    "BAKE_UV_LAYOUT_GUIDE_IMAGE",
    "CREATE_UV_GRID_TEST_MATERIAL",
    "CREATE_UV_MAP_VARIANT",
    "TAG_UV_VARIANT",
    "CREATE_UV_COMPARISON_PREVIEW",
    "ACCEPT_UV_VARIANT",
    "REJECT_UV_VARIANT",
)

TEXTURE_PROJECTION_MODES = ("FLAT", "BOX", "SPHERE", "TUBE")
TEXTURE_EXTENSION_MODES = ("REPEAT", "EXTEND", "CLIP")

UV_DIAGNOSTIC_CHECKS = (
    "missing_uvs",
    "out_of_bounds",
    "overlaps",
    "stretch",
    "material_usage",
)

UV_VALIDATION_CHECKS = (
    "missing_uvs",
    "out_of_bounds",
    "overlaps",
    "zero_area_islands",
    "stretch",
)

UV_PROJECTION_AXES = ("x", "y", "z")
UV_ALIGN_MODES = ("left", "right", "top", "bottom", "center")
UV_DISTRIBUTE_AXES = ("horizontal", "vertical")
UV_TILE_MIN = -10
UV_TILE_MAX = 10

PBR_TEXTURE_ROLES = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "ambient_occlusion",
    "displacement",
    "alpha",
    "emission",
)

PBR_NON_COLOR_ROLES = frozenset(
    {
        "roughness",
        "metallic",
        "normal",
        "ambient_occlusion",
        "displacement",
        "alpha",
    }
)

GENERATED_TEXTURE_PATTERNS = (
    "solid",
    "checker",
    "noise",
    "gradient",
)

TEXTURE_BLEND_MODES = ("replace", "mix", "multiply", "add")

TEXTURE_BAKE_PASS_TYPES = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "ambient_occlusion",
    "emission",
)

GEOMETRY_NODES_PRESETS = (
    "scatter_points",
    "procedural_detail",
    "simple_cables",
    "architectural_array",
    "terrain_displacement",
)

GEOMETRY_NODE_GROUP_TEMPLATES = (
    "point_scatter_group",
    "bevel_detail_group",
    "terrain_noise_group",
)

GEOMETRY_NODE_INPUTS = (
    "density",
    "scale",
    "strength",
    "count",
    "seed",
)

GENERATED_MESH_VARIANTS = (
    "smoothed",
    "displaced",
    "remeshed",
    "voxel_remeshed",
    "quad_remesh_prep",
    "dynamic_topology_detail",
    "multires_sculpt",
    "sculpt_variant",
)

SCULPT_REGION_KINDS = (
    "material",
    "vertex_group",
)

SCULPT_REGION_OPERATIONS = (
    "smooth",
    "inflate",
    "flatten",
)

ADVANCED_SCULPT_BRUSH_TYPES = (
    "clay",
    "clay_strips",
    "crease",
    "pinch",
    "scrape",
    "grab",
    "snake_hook",
    "pose",
)

SCULPT_BRUSH_FALLOFFS = (
    "smooth",
    "linear",
    "sharp",
)

SCULPT_SYMMETRY_AXES = (
    "x",
    "y",
    "z",
)

SCULPT_SYMMETRY_ORIGINS = (
    "object_origin",
    "world_origin",
    "custom",
)

DYNAMIC_TOPOLOGY_DETAIL_METHODS = (
    "relative_detail",
    "constant_detail",
)

PREVIEW_IMAGE_KINDS = (
    "material",
    "uv",
    "paint",
    "bake",
    "generated_mesh",
    "sculpt_region",
)

RENDER_PREVIEW_MODES = (
    "solid",
    "material",
    "rendered",
)

MESH_PROCESSING_LIMITS = {
    "default_max_vertices": 100_000,
    "default_max_polygons": 100_000,
    "generated_copy_max_vertices": 250_000,
    "sculpt_stroke_max_count": 500,
    "texture_image_max_dimension": 4096,
    "texture_paint_stroke_max_count": 1_000,
    "generated_mesh_max_vertices": 250_000,
    "generated_mesh_max_polygons": 250_000,
    "geometry_nodes_max_count": 10_000,
    "preview_image_max_dimension": 1024,
}
