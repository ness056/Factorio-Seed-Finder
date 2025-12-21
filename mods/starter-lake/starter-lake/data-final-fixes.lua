for _, resource in pairs(data.raw["resource"]) do
    resource.map_grid = false
end

data.raw["resource"]["iron-ore"].map_color = { 50, 0, 0 }
data.raw["resource"]["copper-ore"].map_color = { 255, 0, 1 }
data.raw["resource"]["coal"].map_color = { 0, 0, 2 }
data.raw["resource"]["stone"].map_color = { 100, 100, 3 }
data.raw["tile"]["water"].map_color = { 0, 255, 4 }
data.raw["tile"]["grass-1"].map_color = { 0, 100, 5 }

local gen_settings = data.raw["planet"]["nauvis"].map_gen_settings
gen_settings.cliff_settings = nil

local autoplace_settings = gen_settings.autoplace_settings
for k, _ in pairs(autoplace_settings.entity.settings) do
    autoplace_settings.entity.settings[k] = nil
end
for k, _ in pairs(autoplace_settings.tile.settings) do
    if k ~= "water" then
        autoplace_settings.tile.settings[k] = nil
    end
end

for k, _ in pairs(autoplace_settings.decorative.settings) do
    autoplace_settings.decorative.settings[k] = nil
end

gen_settings.autoplace_settings.entity.settings["fish"] = nil

local excluded_entities = {
    ["water"] = true
}
for type, prototypes in pairs(data.raw) do
    for name, proto in pairs(prototypes) do
        if excluded_entities[name] then goto continue end
        if proto.autoplace then
            proto.autoplace = nil
        end
        ::continue::
    end
end

data.raw["noise-function"]["elevation_nauvis_function"].expression = "starting_lake"