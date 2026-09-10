#include "CityBlockGenerator.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
	// The engine cube is 100 units on a side with a centred pivot, so a scale
	// of 1 is 100cm and instances sit half their height above the ground.
	constexpr float EngineCubeSize = 100.f;
}

ACityBlockGenerator::ACityBlockGenerator()
{
	PrimaryActorTick.bCanEverTick = false;

	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);

	Buildings = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("Buildings"));
	Buildings->SetupAttachment(Root);
	Buildings->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	Buildings->SetCollisionObjectType(ECC_WorldStatic);
	Buildings->SetCollisionResponseToAllChannels(ECR_Block);
	Buildings->SetMobility(EComponentMobility::Static);

	Ground = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("Ground"));
	Ground->SetupAttachment(Root);
	Ground->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	Ground->SetCollisionObjectType(ECC_WorldStatic);
	Ground->SetCollisionResponseToAllChannels(ECR_Block);
	Ground->SetMobility(EComponentMobility::Static);

	static ConstructorHelpers::FObjectFinder<UStaticMesh> CubeMesh(TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (CubeMesh.Succeeded())
	{
		Buildings->SetStaticMesh(CubeMesh.Object);
		Ground->SetStaticMesh(CubeMesh.Object);
	}
}

void ACityBlockGenerator::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	Generate();
}

void ACityBlockGenerator::Generate()
{
	if (!Buildings || !Ground)
	{
		return;
	}

	Buildings->ClearInstances();
	Ground->ClearInstances();

	// Seeded rather than global random, so tuning a swing against a skyline
	// does not mean tuning against a different city on every rebuild.
	FRandomStream Random(Seed);

	const float Extent = (GridSize - 1) * BlockSpacing * 0.5f;

	if (bGenerateGround)
	{
		const float GroundSize = GridSize * BlockSpacing + BlockSpacing;
		const float GroundThickness = 200.f;
		Ground->AddInstance(FTransform(
			FRotator::ZeroRotator,
			FVector(0.f, 0.f, -GroundThickness * 0.5f),
			FVector(GroundSize / EngineCubeSize, GroundSize / EngineCubeSize, GroundThickness / EngineCubeSize)));
	}

	for (int32 X = 0; X < GridSize; ++X)
	{
		for (int32 Y = 0; Y < GridSize; ++Y)
		{
			const FVector Center(X * BlockSpacing - Extent, Y * BlockSpacing - Extent, 0.f);

			if (Center.Size2D() < SpawnClearRadius)
			{
				continue;
			}
			if (Random.FRand() < EmptyBlockChance)
			{
				continue;
			}

			const float FootprintX = Random.FRandRange(MinFootprint, MaxFootprint);
			const float FootprintY = Random.FRandRange(MinFootprint, MaxFootprint);

			// Bias height toward the centre so the skyline has a downtown to
			// aim at and a low outskirt to fall into.
			const float DistanceAlpha = FMath::Clamp(1.f - (Center.Size2D() / FMath::Max(1.f, Extent)), 0.f, 1.f);
			const float HeightBias = FMath::Lerp(0.35f, 1.f, DistanceAlpha);
			const float Height = FMath::Lerp(MinHeight, MaxHeight, Random.FRand() * HeightBias);

			// Jitter off the grid line so the streets are not a perfect lattice.
			const FVector Jitter(
				Random.FRandRange(-BlockSpacing, BlockSpacing) * 0.12f,
				Random.FRandRange(-BlockSpacing, BlockSpacing) * 0.12f,
				0.f);

			Buildings->AddInstance(FTransform(
				FRotator(0.f, Random.FRandRange(-6.f, 6.f), 0.f),
				Center + Jitter + FVector(0.f, 0.f, Height * 0.5f),
				FVector(FootprintX / EngineCubeSize, FootprintY / EngineCubeSize, Height / EngineCubeSize)));
		}
	}
}
