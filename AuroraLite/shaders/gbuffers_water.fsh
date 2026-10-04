#version 120

uniform sampler2D gtexture;
uniform sampler2D lightmap;
uniform float frameTimeCounter;
uniform float rainStrength;

varying vec2 texcoord;
varying vec2 lmcoord;
varying vec4 vertColor;
varying vec3 viewNormal;

void main() {
    vec2 wave = vec2(sin(frameTimeCounter * 1.4 + texcoord.y * 18.0), cos(frameTimeCounter * 1.1 + texcoord.x * 15.0)) * 0.006;
    vec4 tex = texture2D(gtexture, texcoord + wave) * vertColor;
    vec3 light = texture2D(lightmap, lmcoord).rgb;
    vec3 water = mix(tex.rgb, vec3(0.08, 0.42, 0.58), 0.42);
    water *= light * (0.9 + 0.1 * max(viewNormal.y, 0.0));
    float alpha = min(tex.a, 0.76);
    gl_FragColor = vec4(water, alpha);
}
