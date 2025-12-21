for _, resource in pairs(data.raw["resource"]) do
    resource.map_grid = false
end

data.raw["resource"]["iron-ore"].map_color = { 0, 0, 50 }
data.raw["resource"]["copper-ore"].map_color = { 1, 0, 255 }
data.raw["resource"]["coal"].map_color = { 2, 0, 0 }
data.raw["resource"]["stone"].map_color = { 3, 100, 100 }
data.raw["tile"]["water"].map_color = { 4, 255, 0 }
data.raw["tile"]["grass-1"].map_color = { 5, 100, 0 }

local gen_settings = data.raw["planet"]["nauvis"].map_gen_settings
gen_settings.cliff_settings = nil

local excluded_entities = {
    ["iron-ore"] = true,
    ["copper-ore"] = true,
    ["coal"] = true,
    ["stone"] = true,
    ["oil"] = true
}

local autoplace_settings = gen_settings.autoplace_settings
for name, _ in pairs(autoplace_settings.entity.settings) do
    if excluded_entities[name] then goto continue end
    autoplace_settings.entity.settings[name] = nil
    ::continue::
end
for name, _ in pairs(autoplace_settings.tile.settings) do
    if excluded_entities[name] then goto continue end
    autoplace_settings.tile.settings[name] = nil
    ::continue::
end

for name, _ in pairs(autoplace_settings.decorative.settings) do
    autoplace_settings.decorative.settings[name] = nil
end

gen_settings.autoplace_settings.entity.settings["fish"] = nil
for type, prototypes in pairs(data.raw) do
    for name, proto in pairs(prototypes) do
        if excluded_entities[name] then goto continue end
        if proto.autoplace then
            proto.autoplace = nil
        end
        ::continue::
    end
end

data.raw["noise-function"]["resource_autoplace_all_patches"].expression = "regular_patches"