done = function(summary, latency, requests)
    io.write("------------------------------\n")
    for _, p in pairs({ 50, 90, 95, 99, 99.999 }) do
        n = latency:percentile(p)
        io.write(string.format("%g%%,%d\n", p, n))
    end
end

-- Lua implementation of PHP scandir function
-- https://stackoverflow.com/questions/5303174/how-to-get-list-of-directories-in-lua
function scandir(directory)
    local i, t, popen = 0, {}, io.popen
    local pfile = popen('ls -A "'..directory..'"')
    for filename in pfile:lines() do
        i = i + 1
        t[i] = filename
    end
    pfile:close()
    return t
end

-- https://stackoverflow.com/questions/78225022/is-there-a-lua-equivalent-of-the-javascript-encodeuri-function
function _encode_uri_char(char)
    return string.format('%%%0X', string.byte(char))
end

function encode_uri(uri)
    return (string.gsub(uri, "[^%a%d%-_%.!~%*'%(%);/%?:@&=%+%$,#]", _encode_uri_char))
end


function file_exists(file)
  local f = io.open(file, "rb")
  if f then f:close() end
  return f ~= nil
end

function lines_from(file)
  if not file_exists(file) then return {} end
  local lines = {}
  for line in io.lines(file) do 
    lines[#lines + 1] = line
  end
  return lines
end

function generate_density()
    lines = lines_from("/benchmark/wrk/density.csv")
    max = lines[500]
    indicies = {}
    for j=1, 100000 do
        rand = math.random(max) - 1
        i = 1
        for k, v in pairs(lines) do
            i = k
            if rand < tonumber(v) then
                indicies[j] = i
                break
            end
        end
    end
    return indicies
end

reqs = {}
density = {}
init = function(args)
    math.randomseed(1)
    -- build table of potential requests
    for i = 0, 499 do
        local r = {}
        for _, line in pairs(scandir("/benchmark/wrk/http/_all")) do
            table.insert(r, wrk.format(nil, "/_all/" .. encode_uri(line)))
        end
        for _, line in pairs(scandir("/benchmark/wrk/http/" .. i)) do
            table.insert(r, wrk.format(nil, "/" .. i .. "/" .. encode_uri(line)))
        end
        reqs[i] = table.concat(r)
    end

    -- generate density table
    density = generate_density()
end

request = function()
    return reqs[density[math.random(100000)]]
end


