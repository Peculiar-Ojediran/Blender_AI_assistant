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
    "Base Color",
    "Metallic",
    "Roughness",
    "Alpha",
    "Normal",
    "Emission Color",
    "Emission Strength",
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
)

TEXTURE_PROJECTION_MODES = ("FLAT", "BOX", "SPHERE", "TUBE")
TEXTURE_EXTENSION_MODES = ("REPEAT", "EXTEND", "CLIP")

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
